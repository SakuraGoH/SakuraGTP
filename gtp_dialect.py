"""引擎方言层：探测能力 + 把野狐需求翻译成该引擎认识的 GTP。

FoxGTP 之所以兼容面广，核心是它**只碰 GTP v1 的 11 条核心命令**，把
``analyze`` / ``kata-*`` 这类各家自创命令全部绕开。本模块沿用这个思路，
再往前一步：先探测引擎支持什么，再挑最保守、最通用的写法。

探测手段（按 GTP 规范，且不会让引擎报错退出）：

    protocol_version              —— 必答，顺带判断引擎是否回显命令号
    name / version                —— 识别引擎家族
    list_commands                 —— 拿到命令全集
    known_command <cmd>           —— list_commands 不可用时的兜底

翻译原则：

* 棋盘设置：boardsize / clear_board / komi 永远只用这三条；
* 让子：优先 ``set_free_handicap``（接受任意坐标），不支持就逐子 ``play B``；
* 时间：优先 ``time_settings`` + ``time_left``；把「加拿大读秒」和
  「围棋常用读秒」两种口径区分开（野狐读秒是「多少秒 N 次」）；
* 落子：``genmove``；KataGo 有 ``kata-genmove_analyze`` 时用它（顺带出胜率），
  没有就老老实实 ``genmove``；
* 点目：有 ``final_score`` 才发，没有就按野狐协议回 ``error``
  （协议明确允许 ``$AFSCORE,0,error``，比乱猜一个结果安全）。
"""

import math
import re

VERTEX_LETTERS = "ABCDEFGHJKLMNOPQRST"


# ---------------------------------------------------------------------------- 引擎画像
class EngineProfile:
    """一个引擎的能力画像。"""

    def __init__(self):
        self.name = ""
        self.version = ""
        self.family = "unknown"      # katago / leela / gnugo / fuego / pachi / unknown
        self.commands = set()
        self.echoes_id = True
        self.list_ok = False
        self.probe_ok = False

    # -- 能力判断 -----------------------------------------------------------
    def _has(self, cmd, default=True):
        if self.list_ok:
            return cmd in self.commands
        return default

    @property
    def kata(self):
        if self.family == "katago":
            return True
        if self.list_ok:
            return ("kata-genmove_analyze" in self.commands
                    or "kata-set-param" in self.commands)
        return False

    @property
    def kata_analyze(self):
        return self._has("kata-genmove_analyze", self.family == "katago")

    @property
    def lz_analyze(self):
        return self._has("lz-genmove_analyze", False)

    @property
    def undo(self):
        return self._has("undo", self.family in ("katago", "leela"))

    @property
    def final_score(self):
        return self._has("final_score", True)

    @property
    def set_free_handicap(self):
        return self._has("set_free_handicap", True)

    @property
    def time_settings(self):
        return self._has("time_settings", True)

    @property
    def time_left(self):
        return self._has("time_left", True)

    @property
    def kata_rules(self):
        return self._has("kata-set-rules", self.family == "katago")

    @property
    def stop(self):
        return self._has("stop", self.family in ("katago", "leela"))

    @property
    def display_name(self):
        bits = [b for b in (self.name, self.version) if b]
        return " ".join(bits) if bits else (self.family or "unknown")

    def summary(self):
        caps = []
        if self.kata:
            caps.append("kata")
        if self.kata_analyze:
            caps.append("kata-analyze")
        if self.lz_analyze:
            caps.append("lz-analyze")
        if self.undo:
            caps.append("undo")
        if self.final_score:
            caps.append("final_score")
        if self.set_free_handicap:
            caps.append("free-handicap")
        if self.time_settings:
            caps.append("time")
        caps.append("id回显" if self.echoes_id else "id不回显")
        return "%s(%s) [%s]" % (self.display_name, self.family, ",".join(caps))


def _family_from_text(text, hint=""):
    blob = ("%s %s" % (text or "", hint or "")).lower()
    if "katago" in blob or "kata-go" in blob:
        return "katago"
    if "leela" in blob or "leelaz" in blob or blob.strip().startswith("lz"):
        return "leela"
    if "gnu go" in blob or "gnugo" in blob:
        return "gnugo"
    if "fuego" in blob:
        return "fuego"
    if "pachi" in blob:
        return "pachi"
    return "unknown"


def _detect_echo(resp):
    """从一条响应判断引擎是否回显命令号。

    返回 True / False / None（判断不了）。
    只看 ``=3 内容`` 与 ``= 内容`` 两种形态：空正文的 "=3" 无法与
    「正文就是一个 3」区分，直接放弃判断。
    """
    if resp is None:
        return None
    raw = (resp.raw or "").lstrip()
    if not raw.startswith("="):
        return None
    rest = raw[1:].lstrip()
    if re.match(r"^\d+\s+\S", rest):
        return True
    if rest and not re.match(r"^\d+$", rest):
        return False
    return None


def probe(session, hint="", timeout=1.0, first_resp=None):
    """探测引擎能力。必须保证此时命令队列是空的（刚启动时调用）。

    ``first_resp`` 用来复用调用方已经拿到的 ``protocol_version`` 响应，
    避免同一条命令发两次（日志里会出现两条 protocol_version）。
    """
    prof = EngineProfile()

    r = first_resp if first_resp is not None else session.call(
        "protocol_version", timeout=timeout)
    if r is not None:
        prof.probe_ok = True
        prof.version = (r.body or "").strip().split("\n")[0][:60]

    r = session.call("name", timeout=timeout)
    name_resp = r
    if r is not None and r.ok:
        prof.name = (r.body or "").strip().split("\n")[0][:80]

    r = session.call("list_commands", timeout=max(timeout, 1.5))
    list_resp = r
    if r is not None and r.ok and r.body.strip():
        cmds = set()
        for line in r.body.replace(",", " ").split():
            line = line.strip()
            if line and re.match(r"^[a-zA-Z][a-zA-Z0-9_\-]*$", line):
                cmds.add(line)
        if cmds:
            prof.commands = cmds
            prof.list_ok = True

    prof.family = _family_from_text("%s %s" % (prof.name, prof.version), hint)

    # 回显判断：优先看 name（正文一定非数字），其次 list_commands
    detected = _detect_echo(name_resp)
    if detected is None:
        detected = _detect_echo(list_resp)
    if detected is None and session.saw_id_token:
        detected = True
    if detected is not None:
        prof.echoes_id = detected

    if not prof.list_ok:
        # 兜底：只确认我们真正会用到的几条命令
        interesting = ["kata-genmove_analyze", "kata-set-param", "kata-set-rules",
                       "lz-genmove_analyze", "undo", "final_score",
                       "set_free_handicap", "time_settings", "time_left", "stop"]
        found = set()
        for cmd in interesting:
            rr = session.call("known_command %s" % cmd, timeout=min(timeout, 0.8))
            if rr is not None and rr.ok and rr.body.strip().lower() in ("true", "1", "yes"):
                found.add(cmd)
        if found:
            prof.commands = found
            # 只拿到部分命令：默认核心命令可用（list_ok 仍为 False，走默认值）
    return prof


# ---------------------------------------------------------------------------- 方言
class Dialect:
    """按引擎画像生成实际要发的 GTP 命令。"""

    def __init__(self, profile=None):
        self.profile = profile or EngineProfile()

        # 与 FoxGTP 一一对应的选项（野狐手册 4.4.1 / 4.4.2）
        self.use_go_byoyomi = False          # True: s 表示读秒次数
        self.use_data_transfer_time = False  # 从读秒时间里扣掉传输耗时
        self.data_transfer_time = 1
        self.specify_ai_byoyomi = False      # 强制指定 AI 读秒时间
        self.ai_byoyomi_time = 5

        # 用户设置的计算量（KataGo 用；非 KataGo 用来给读秒时间封顶）
        self.max_time = 0.0
        self.max_visits = 0
        self.max_playouts = 0

        self.board_size = 19
        # 当前对局规则里的时间（由 bridge 维护）
        self.main_time = 0
        self.byo_time = 0
        self.byo_count = 0

    # ------------------------------------------------------------------ 基础
    @staticmethod
    def format_komi(komi):
        """贴目格式化：整数不带小数点，其余最多两位（不学 FoxGTP 的 %.1f 丢精度）。"""
        try:
            k = float(komi)
        except (TypeError, ValueError):
            return "6.5"
        if abs(k - round(k)) < 1e-9:
            return "%d" % int(round(k))
        s = ("%.2f" % k).rstrip("0").rstrip(".")
        return s or "0"

    def _byoyomi(self, byo_time, byo_count):
        """把野狐的读秒口径换算成引擎要的口径。"""
        byo = max(0, int(byo_time))
        count = max(1, int(byo_count))
        if self.specify_ai_byoyomi and self.ai_byoyomi_time > 0:
            byo = int(self.ai_byoyomi_time)
        elif self.use_data_transfer_time:
            byo = max(1, byo - max(0, int(self.data_transfer_time)))
        if not self.profile.kata and self.max_time and self.max_time > 0:
            # 非 KataGo 引擎没有 maxTime 参数，用读秒时间封顶，
            # 免得它把整个读秒周期算满导致野狐超时（FoxGTP 也有同款选项）
            byo = max(1, min(byo, int(math.ceil(self.max_time))))
        stones = count if self.use_go_byoyomi else 1
        return byo, stones

    # ------------------------------------------------------------------ 对局设置
    def setup_commands(self, board_size, komi, handicap_vertices, rule=""):
        """返回开新局要发的一串命令（不含命令号）。

        顺序与 FoxGTP 一致：clear_board → boardsize → komi → time_settings
        → 让子。先 clear_board 可以保证引擎无论之前处于什么状态都回到干净局面。
        """
        cmds = []
        self.board_size = int(board_size or 19)
        cmds.append("clear_board")
        cmds.append("boardsize %d" % self.board_size)
        cmds.append("komi %s" % self.format_komi(komi))
        rule_cmd = self.rules_command(rule)
        if rule_cmd:
            cmds.append(rule_cmd)
        cmds.extend(self.time_settings_commands())
        cmds.extend(self.handicap_commands(handicap_vertices))
        return cmds

    def time_settings_commands(self, main_time=None, byo_time=None, byo_count=None):
        if main_time is None:
            main_time = self.main_time
        if byo_time is None:
            byo_time = self.byo_time
        if byo_count is None:
            byo_count = self.byo_count
        if not self.profile.time_settings:
            return []
        byo, stones = self._byoyomi(byo_time, byo_count)
        return ["time_settings %d %d %d" % (max(0, int(main_time)), byo, stones)]

    def time_left_commands(self, color, main_time, byo_time, byo_count):
        """每手同步剩余时间。

        GTP 的 ``time_left C m b``：m 为本方剩余保留时间，b 为读秒周期。
        保留时间用完后 m 必须给 0，引擎才会进入读秒计算。
        """
        if not self.profile.time_left:
            return []
        byo, _stones = self._byoyomi(byo_time, byo_count)
        main = max(0, int(main_time))
        return ["time_left %s %d %d" % (color.upper(), main, byo)]

    def rules_command(self, rule):
        rule = (rule or "").strip().lower()
        if not rule:
            return ""
        if not self.profile.kata_rules:
            return ""
        mapping = {
            "chinese": "chinese",
            "japanese": "japanese",
            "korean": "korean",
            "tromp-taylor": "tromp-taylor",
            "aga": "aga",
            "nz": "new-zealand",
            "new-zealand": "new-zealand",
        }
        name = mapping.get(rule, rule)
        return "kata-set-rules %s" % name

    def handicap_commands(self, vertices):
        """让子：优先 set_free_handicap；不支持就逐子 play B。"""
        verts = [v for v in (vertices or []) if v]
        if not verts:
            return []
        if self.profile.set_free_handicap:
            return ["set_free_handicap " + " ".join(verts)]
        return ["play B %s" % v for v in verts]

    # ------------------------------------------------------------------ 行棋
    def play_command(self, color, vertex):
        color = color.upper()
        if vertex in (None, "", "pass", "PASS"):
            return "play %s pass" % color
        return "play %s %s" % (color, vertex)

    def genmove_command(self, color, want_analysis=True):
        """返回 (命令, 模式)。模式: plain / kata-analyze / lz-analyze。"""
        color = color.upper()
        if want_analysis and self.profile.kata_analyze:
            interval = 50 if (self.max_time and self.max_time <= 10) else 100
            return ("kata-genmove_analyze %s interval %d maxmoves 12" % (color, interval),
                    "kata-analyze")
        return ("genmove %s" % color, "plain")

    def param_commands(self):
        """计算量参数（只有 KataGo 认识 kata-set-param）。"""
        cmds = []
        if not self.profile.kata:
            return cmds
        if self.max_time and self.max_time > 0:
            cmds.append("kata-set-param maxTime %.2f" % float(self.max_time))
        else:
            cmds.append("kata-set-param maxTime 1e20")
        if self.max_visits and self.max_visits > 0:
            cmds.append("kata-set-param maxVisits %d" % int(self.max_visits))
        else:
            cmds.append("kata-set-param maxVisits 100000000")
        if self.max_playouts and self.max_playouts > 0:
            cmds.append("kata-set-param maxPlayouts %d" % int(self.max_playouts))
        return cmds

    def final_score_command(self):
        if not self.profile.final_score:
            return None
        return "final_score"

    def stop_command(self):
        return "stop" if self.profile.stop else None

    # ------------------------------------------------------------------ 解析
    def parse_genmove(self, body):
        """从 genmove / kata-genmove_analyze 的响应里取落子。

        返回 ("move", "Q16") / ("pass", None) / ("resign", None) / (None, None)
        """
        text = (body or "").strip()
        if not text:
            return None, None
        # 多行时取最后一个非空行（analyze 的最后一行才是落子）
        lines = [ln.strip() for ln in text.replace("\r", "\n").split("\n") if ln.strip()]
        if not lines:
            return None, None
        candidates = [lines[-1]]
        if len(lines) > 1:
            candidates.extend(reversed(lines[:-1]))
        for line in candidates:
            tokens = re.split(r"[\s,;]+", line)
            tokens = [t for t in tokens if t]
            if not tokens:
                continue
            lowered = [t.lower().strip(".") for t in tokens]
            if "resign" in lowered:
                return "resign", None
            if "pass" in lowered:
                return "pass", None
            # 常见前缀：play / move
            for tok in reversed(tokens):
                tok = tok.strip(".")
                if re.match(r"^[A-HJ-Ta-hj-t]\d{1,2}$", tok):
                    return "move", tok.upper()
        return None, None

    def parse_score(self, body):
        """把 final_score 结果翻译成野狐 $AFSCORE 的口径。

        final_score 的合法返回：``B+3.5`` / ``W+R`` / ``0`` / ``Draw``，
        但实测各家写法五花八门：``B+3``、``W+Resign``、``Black wins by 3.5``、
        ``white+1.5``、``0.5``（无胜方）……这里统一收敛。
        """
        text = (body or "").strip()
        if not text:
            return "error"
        lines = [ln.strip() for ln in text.replace("\r", "\n").split("\n") if ln.strip()]
        if not lines:
            return "error"
        text = lines[0]

        low = text.lower()
        if low in ("0", "draw", "jigo", "tie", "0.0"):
            return "0"

        # 明确写出胜方的情况
        winner = None
        m = re.match(r"^\s*([bBwW])\s*([+\-])\s*(.+)$", text)
        if m:
            winner = m.group(1).upper()
            rest = m.group(3).strip()
        else:
            m = re.match(r"^\s*(black|white|b|w)\b[^0-9+\-]*(.*)$", low)
            if m:
                winner = "B" if m.group(1).startswith("b") else "W"
                rest = m.group(2).strip()
            else:
                m = re.search(r"\b(black|white)\b.*?(?:by|win[s]?)?\s*([0-9]+(?:\.[0-9]+)?)", low)
                if m:
                    winner = "B" if m.group(1) == "black" else "W"
                    rest = m.group(2)
                else:
                    nums = re.findall(r"[0-9]+(?:\.[0-9]+)?", text)
                    if nums and not re.search(r"[bBwW]", text):
                        return "error"
                    rest = nums[0] if nums else ""

        if winner is None:
            return "error"

        if re.search(r"r\b|resign|中盘|投子", low):
            return "%s+R" % winner
        num = re.search(r"[0-9]+(?:\.[0-9]+)?", rest or text)
        if not num:
            return "%s+R" % winner
        try:
            val = float(num.group(0)) * 100.0
        except ValueError:
            return "error"
        return "%s+%d" % (winner, int(round(val)))
