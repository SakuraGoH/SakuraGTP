"""GTP 会话层：把「发命令 / 收响应」这件事做对。

这一层是从 FoxGTP 的逆向结果里抽象出来的，专门解决兼容性：

1. 只用 GTP v1 核心命令，绝不在通用路径上发 kata-* 之类扩展命令；
2. 响应解析必须同时容忍三种风格（各家引擎写法不一）：

       =1 Q16          ← 带命令号（GTP 规范写法，FoxGTP 只认这种）
       = Q16           ← 不带命令号（标准输出，很多引擎如此）
       play Q16        ← 裸行（KataGo 的 analyze 类命令最后一行）

3. 容忍引擎把名字/前缀写进响应里，例如 ``Leela: Q16``、``GNU Go: pass``；
4. 计算过程里的 ``=`` / ``?`` 不能把响应切错（只看「行首」的标记）；
5. 引擎不回显 id 时，按「先发先回」把响应配给最早未完成的命令（FoxGTP 因为
   强制要求回显 id，遇到不回显的引擎就只能失败 —— 这一点我们做得比它宽）。

命令号永远由本层分配并随命令发出；``id`` 缺失时退回 FIFO 匹配。
"""

import re
import threading
import time

# 行首标记：'=' 成功 / '?' 失败
_MARK_RE = re.compile(r"^([=?])\s*(.*)$")
# 命令号（只在确认存在同号待完成命令时才认作 id）
_ID_RE = re.compile(r"^(\d+)(?=$|[\s])")

# GTP 规范里的顶点：A-T 跳过 I
_VERTEX_RE = re.compile(r"^[A-HJ-Ta-hj-t](?:[1-9]|1[0-9]|2[0-5])$")

# 需要多行累积响应体的命令（list_commands 通常一行一个命令名）
_MULTILINE_PURPOSES = {"list_commands"}

# 这些命令正常返回空正文，所以 "=3" 这种「数字结尾」应视为命令号
_EMPTY_BODY_PURPOSES = {
    "clear_board", "boardsize", "komi", "play", "time_settings", "time_left",
    "set_free_handicap", "fixed_handicap", "undo", "stop", "quit",
    "kata-set-param", "kata-set-rules",
    # KataGo 的 analyze 类命令先回一个空响应当作 ack，真正落子在后面的
    # "play XXX" 裸行里；这里允许空正文才能按 id 认领这个 ack。
    "analyze",
}

# 引擎常见的响应前缀，例如 "Leela:" / "GNU Go:" / "Pachi:"
_PREFIX_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 _\-\.]{0,23}:\s+")


class GTPResponse:
    """一条完整的 GTP 响应。"""

    __slots__ = ("ok", "id", "body", "raw", "purpose")

    def __init__(self, ok=True, id=None, body="", raw="", purpose=""):
        self.ok = ok
        self.id = id
        self.body = body or ""
        self.raw = raw or ""
        self.purpose = purpose or ""

    def __repr__(self):
        return "GTPResponse(ok=%r, id=%r, purpose=%r, body=%r)" % (
            self.ok, self.id, self.purpose, self.body)


class _Pending:
    __slots__ = ("id", "purpose", "created", "done", "response")

    def __init__(self, cid, purpose):
        self.id = cid
        self.purpose = purpose
        self.created = time.time()
        self.done = threading.Event()
        self.response = None


def strip_engine_prefix(text):
    """去掉 "Leela: " / "GNU Go: " 之类前缀，最多去两层。"""
    text = (text or "").strip()
    for _ in range(2):
        m = _PREFIX_RE.match(text)
        if not m:
            break
        rest = text[m.end():].strip()
        # 只有当前缀后面还像内容时才剥离，避免把 "B:3.5" 这类吃掉
        if rest:
            text = rest
        else:
            break
    return text


def looks_like_vertex(tok):
    return bool(_VERTEX_RE.match(tok or ""))


class GTPSession:
    """串行化的 GTP 会话（线程安全）。"""

    def __init__(self, write, on_log=None, on_line=None,
                 on_stream=None, on_response=None):
        self._write = write                # write(str) -> bool
        self.on_log = on_log
        self.on_line = on_line             # 原始行（给 UI）
        self.on_stream = on_stream         # (purpose, line) 分析/中间输出
        self.on_response = on_response     # (GTPResponse)

        self._lock = threading.RLock()
        self._cv = threading.Condition(self._lock)
        self._next_id = 0
        self._pending = []                 # list[_Pending]，按发出顺序
        self._open = None                  # 正在累积的多行响应 (pending, resp)
        self._open_deadline = 0.0
        self._stopped = False

        self.last_rtt = 0.0
        # 引擎是否回显命令号（探测阶段设置；False 时响应里的数字一律当正文）
        self.echoes_id = True
        self.saw_id_token = False   # 是否出现过 "=3 内容" 这种明确带 id 的响应
        self._orphan_skip = 0       # 待丢弃的「无命令号游离响应」条数
        # 正在等待落子（analyze 的 info/play 行需要按流处理）
        self.streaming = False
        self._watch_thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._watch_thread.start()

    # ------------------------------------------------------------------ 基础
    def log(self, msg):
        if self.on_log:
            self.on_log(msg)

    def reset(self, reason="", orphan_skip=False):
        """引擎重启/断开/新对局时清空所有待完成命令。

        ``orphan_skip=True`` 用于「命令还在引擎肚子里，但我们不要结果了」的场景
        （比如思考中途开了新局）。此时后续那几条没有命令号的响应必须丢弃，
        否则会被 FIFO 错配给新命令。
        """
        with self._lock:
            pending = self._pending
            self._pending = []
            self._open = None
            self.streaming = False
            if orphan_skip:
                self._orphan_skip += len(pending)
            for p in pending:
                p.response = GTPResponse(ok=False, body="cancelled", purpose=p.purpose)
                p.done.set()
            if reason:
                self.log("会话重置: %s（丢弃 %d 条待完成命令）" % (reason, len(pending)))

    def _alloc_id(self):
        with self._lock:
            self._next_id += 1
            return self._next_id

    def send(self, command, purpose=""):
        """发送命令，返回分配的命令号。"""
        with self._lock:
            cid = self._alloc_id()
            p = _Pending(cid, purpose)
            self._pending.append(p)
            line = "%d %s" % (cid, command)
            if self.on_line:
                self.on_line(">>> " + line)
            ok = self._write(line)
            if not ok:
                self.log("GTP 发送失败（引擎未运行？）: %s" % line)
                try:
                    self._pending.remove(p)
                except ValueError:
                    pass
                p.response = GTPResponse(ok=False, body="write failed", purpose=purpose)
                p.done.set()
            return cid

    def send_raw(self, line, purpose=""):
        """发送不带命令号的行（quit / stop 等收尾命令）。"""
        if self.on_line:
            self.on_line(">>> " + line)
        return self._write(line)

    # ------------------------------------------------------------------ 同步调用
    def call(self, command, timeout=2.0, purpose=""):
        """发送并等待这条命令自己的响应（阻塞，供探测阶段使用）。"""
        purpose = purpose or command.split(" ")[0]
        with self._lock:
            cid = self._alloc_id()
            p = _Pending(cid, purpose)
            self._pending.append(p)
            line = "%d %s" % (cid, command)
            if self.on_line:
                self.on_line(">>> " + line)
            ok = self._write(line)
            if not ok:
                try:
                    self._pending.remove(p)
                except ValueError:
                    pass
                return None
        if not p.done.wait(timeout):
            with self._lock:
                try:
                    self._pending.remove(p)
                except ValueError:
                    pass
            self.log("GTP 等待超时: %s（%.1fs）" % (command, timeout))
            return None
        return p.response

    def has_pending(self, purpose=None):
        with self._lock:
            if purpose is None:
                return bool(self._pending)
            return any(p.purpose == purpose for p in self._pending)

    def pending_count(self):
        """当前还没收到回执的命令数（棋谱分块重放时用来做流控）。"""
        with self._lock:
            return len(self._pending)

    def complete_pending(self, purpose, body="", ok=True):
        """用一条「裸行」回答完成某类命令（KataGo analyze 的最终 play 行）。"""
        with self._lock:
            target = None
            for p in reversed(self._pending):
                if p.purpose == purpose:
                    target = p
                    break
            if target is None:
                return False
            self._pending.remove(target)
        resp = GTPResponse(ok=ok, body=body, purpose=purpose)
        target.response = resp
        self._deliver(target, resp)
        return True

    def pending_age(self, purpose=None):
        """最早一条未完成命令已经等了多久（秒），没有则 0。"""
        with self._lock:
            candidates = [p for p in self._pending
                          if purpose is None or p.purpose == purpose]
            if not candidates:
                return 0.0
            return time.time() - min(p.created for p in candidates)

    # ------------------------------------------------------------------ 收行
    def on_engine_line(self, raw_line):
        if raw_line is None:
            return
        line = raw_line.rstrip("\r\n")
        if self.on_line:
            self.on_line(line)
        if not line.strip():
            self._finish_open("blank")
            return

        marker = _MARK_RE.match(line)
        if marker:
            self._finish_open("new-response")
            self._begin_response(marker.group(1), marker.group(2).strip(), line)
            return

        # 非标记行：可能是多行响应体的续行、分析流、或裸回答
        with self._lock:
            opening = self._open
        if opening is not None:
            pending, resp = opening
            if pending.purpose in _MULTILINE_PURPOSES:
                resp.body = (resp.body + "\n" + line.strip()).strip()
                resp.raw = (resp.raw + "\n" + line).strip()
                with self._lock:
                    self._open_deadline = time.time() + 0.35
                return

        self._route_stream(line)

    def _begin_response(self, mark, rest, raw):
        ok = mark == "="
        cid = None
        body = rest

        m = _ID_RE.match(body) if self.echoes_id else None
        if m:
            candidate = int(m.group(1))
            rest_after = body[m.end():]
            pending = None
            with self._lock:
                for p in self._pending:
                    if p.id == candidate:
                        pending = p
                        break
            if pending is not None:
                # 只有「后面还有内容」或「命令本就返回空正文」时才敢认命令号，
                # 否则 "=2"（protocol_version 返回 2，且本命令 id 恰好是 2）
                # 会被误当成命令号。
                if rest_after.strip() or pending.purpose in _EMPTY_BODY_PURPOSES:
                    cid = candidate
                    body = rest_after.strip()
                    if re.match(r"^\d+\s+\S", rest):
                        self.saw_id_token = True
        body = strip_engine_prefix(body)

        resp = GTPResponse(ok=ok, id=cid, body=body, raw=raw)
        pending = self._take_pending(cid)
        if pending is None:
            if cid is None:
                with self._lock:
                    if self._orphan_skip > 0:
                        self._orphan_skip -= 1
                        self.log("丢弃一条游离响应（无可匹配命令）: %r" % raw)
                        return
            # 没有匹配的待完成命令：当作引擎主动输出
            self._route_stream(raw)
            return
        resp.purpose = pending.purpose
        pending.response = resp

        if pending.purpose in _MULTILINE_PURPOSES:
            with self._lock:
                self._open = (pending, resp)
                self._open_deadline = time.time() + 0.35
            if not body:
                # 有些引擎先 "=" 再分行给内容；等续行
                return
            return

        self._deliver(pending, resp)

    def _take_pending(self, cid):
        with self._lock:
            if cid is not None:
                for p in self._pending:
                    if p.id == cid:
                        self._pending.remove(p)
                        return p
                return None
            if self._pending:
                # 引擎不回显 id：按先发先回
                return self._pending.pop(0)
            return None

    def _finish_open(self, why):
        with self._lock:
            opening = self._open
            self._open = None
        if opening is None:
            return
        pending, resp = opening
        self._deliver(pending, resp)

    def _deliver(self, pending, resp):
        if self.last_rtt <= 0:
            self.last_rtt = time.time() - pending.created
        else:
            self.last_rtt = 0.7 * self.last_rtt + 0.3 * (time.time() - pending.created)
        if self.on_response:
            try:
                self.on_response(resp)
            except Exception as e:      # 回调异常不能拖垮读线程
                self.log("响应回调异常: %s" % e)
        pending.done.set()

    # ------------------------------------------------------------------ 分析流
    def _route_stream(self, line):
        text = line.strip()
        if not text:
            return
        purpose = ""
        with self._lock:
            for p in reversed(self._pending):
                if p.purpose in ("genmove", "analyze"):
                    purpose = p.purpose
                    break
        if not purpose and self.streaming:
            purpose = "analyze"
        if purpose and self.on_stream:
            try:
                self.on_stream(purpose, text)
            except Exception as e:
                self.log("分析流回调异常: %s" % e)

    # ------------------------------------------------------------------ 看门狗
    def _watch_loop(self):
        while not self._stopped:
            time.sleep(0.1)
            try:
                with self._lock:
                    opening = self._open
                    deadline = self._open_deadline
                if opening is not None and time.time() >= deadline:
                    self._finish_open("idle")
            except Exception:
                pass

    def stop(self):
        self._stopped = True
