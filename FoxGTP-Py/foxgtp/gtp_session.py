"""GTP session: command ids, response matching and tolerant line handling.

The session owns *one* engine connection and turns a byte stream into
``GtpResponse`` objects.  It does not know anything about Wild Fox or about
which commands are useful; that is the dialect/controller's job.

Compatibility notes (these are the rules that make odd engines work):

* responses may or may not echo the command id -> match by id first, then FIFO;
* a bare ``play Q16`` line can be a genmove answer (KataGo's analyze commands);
* ``=`` / ``?`` only count at the start of a response line, so analysis text
  containing those characters cannot split a response;
* ``list_commands`` / arbitrary shell commands may span several lines;
* after abandoning commands (new game while the engine is thinking) the next
  id-less responses are discarded instead of being mis-assigned.
"""

import re
import threading
import time
from dataclasses import dataclass

from . import gtp_protocol
from .gtp_protocol import parse_marker, split_id, strip_engine_prefix

# purposes whose replies are known to be multi-line (or unknown-size)
_MULTILINE_PURPOSES = {"list_commands", "raw", "known_command_all"}

# commands that legitimately answer with an empty body (so "=12" means id 12)
_EMPTY_BODY_PURPOSES = {
    "clear_board", "boardsize", "komi", "play", "time_settings", "time_left",
    "set_free_handicap", "fixed_handicap", "place_free_handicap", "undo",
    "stop", "ponderhit", "quit", "kata-set-param", "kata-set-rules",
    "lz-analyze", "kata-analyze", "analyze",
}


@dataclass
class GtpResponse:
    ok: bool
    id: int
    body: str
    raw: str
    purpose: str

    def __repr__(self):
        return "GtpResponse(ok=%r, id=%r, purpose=%r, body=%r)" % (
            self.ok, self.id, self.purpose, self.body)


class _Pending:
    __slots__ = ("id", "purpose", "created", "event", "response", "multiline")

    def __init__(self, cid, purpose, multiline):
        self.id = cid
        self.purpose = purpose
        self.created = time.time()
        self.event = threading.Event()
        self.response = None
        self.multiline = multiline


class GtpSession:
    def __init__(self, transport=None, on_line=None, on_stream=None,
                 on_response=None, on_log=None, on_unsolicited=None):
        self.transport = transport
        self.on_line = on_line              # every raw line, either direction
        self.on_stream = on_stream          # (purpose, text) analysis/stream lines
        self.on_response = on_response      # (GtpResponse)
        self.on_log = on_log
        self.on_unsolicited = on_unsolicited

        self.echoes_id = True
        self.saw_id_token = False            # saw an unambiguous "=3 text" reply
        self.streaming = False
        self._next_id = 0
        self._pending = []
        self._open = None                   # (pending, response) being accumulated
        self._open_deadline = 0.0
        self._orphan_skip = 0
        self._lock = threading.RLock()
        self._closed = False
        self._monitor = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor.start()

        if transport is not None:
            transport.on_line = self.feed_line

    # ------------------------------------------------------------------ logging
    def log(self, message):
        if self.on_log:
            self.on_log(message)

    # ------------------------------------------------------------------ sending
    def attach(self, transport):
        self.transport = transport
        if transport is not None:
            transport.on_line = self.feed_line

    def _write(self, line):
        if self.transport is None:
            return False
        return self.transport.send(line)

    def send(self, command, purpose="", expect_reply=True, multiline=None):
        """Send a command, return its id (or ``None`` when nothing is written)."""
        purpose = purpose or (command.split(" ")[0] if command else "")
        if multiline is None:
            multiline = purpose in _MULTILINE_PURPOSES
        if self.on_line:
            self.on_line(">>> " + command)
        if not expect_reply:
            self._write(command)
            return None
        with self._lock:
            self._next_id += 1
            cid = self._next_id
            pending = _Pending(cid, purpose, multiline)
            self._pending.append(pending)
        if not self._write("%d %s" % (cid, command)):
            with self._lock:
                if pending in self._pending:
                    self._pending.remove(pending)
            self.log("发送失败（引擎未连接）: %s" % command)
            pending.response = GtpResponse(False, cid, "not connected", command, purpose)
            pending.event.set()
            return None
        return cid

    def request(self, command, timeout=3.0, purpose="", multiline=None):
        """Send and block for the reply (probe / GTP shell / tests)."""
        purpose = purpose or (command.split(" ")[0] if command else "")
        if multiline is None:
            multiline = purpose in _MULTILINE_PURPOSES
        with self._lock:
            self._next_id += 1
            cid = self._next_id
            pending = _Pending(cid, purpose, multiline)
            self._pending.append(pending)
        if self.on_line:
            self.on_line(">>> " + command)
        if not self._write("%d %s" % (cid, command)):
            with self._lock:
                if pending in self._pending:
                    self._pending.remove(pending)
            return None
        if not pending.event.wait(timeout):
            with self._lock:
                if pending in self._pending:
                    self._pending.remove(pending)
            self.log("等待超时: %s（%.1fs）" % (command, timeout))
            return None
        return pending.response

    def send_raw(self, line):
        if self.on_line:
            self.on_line(">>> " + line)
        return self._write(line)

    # ------------------------------------------------------------------ receiving
    def feed_line(self, line):
        text = "" if line is None else line.rstrip("\r\n")
        if self.on_line:
            self.on_line(text)
        if self._closed:
            return
        if gtp_protocol.is_blank(text):
            self._finish_open("blank")
            return

        marker = parse_marker(text)
        if marker is None:
            self._handle_plain_line(text)
            return

        self._finish_open("new-response")
        ok, rest = marker
        self._begin_response(ok, rest, text)

    def _handle_plain_line(self, text):
        with self._lock:
            opening = self._open
        if opening is not None:
            pending, response = opening
            response.body = (response.body + "\n" + text.strip()).strip()
            response.raw = (response.raw + "\n" + text).strip()
            with self._lock:
                self._open_deadline = time.time() + 0.3
            return
        if self.streaming and self.on_stream:
            self.on_stream("analyze", text.strip())
            return
        if self.on_unsolicited:
            self.on_unsolicited(text)

    def _begin_response(self, ok, rest, raw):
        body = strip_engine_prefix(rest)
        cid = None
        if self.echoes_id:
            with self._lock:
                known = {pending.id for pending in self._pending}
            candidate, stripped = split_id(body, known)
            if candidate is not None:
                cid = candidate
                body = strip_engine_prefix(stripped)
                if re.match(r"^\d+\s+\S", rest):
                    self.saw_id_token = True

        response = GtpResponse(ok=ok, id=cid, body=body, raw=raw, purpose="")
        pending = self._take_pending(cid)
        if pending is None:
            with self._lock:
                if cid is None and self._orphan_skip > 0:
                    self._orphan_skip -= 1
                    self.log("丢弃一条无主响应: %r" % raw)
                    return
            if self.streaming and self.on_stream:
                self.on_stream("analyze", body or raw)
                return
            if self.on_unsolicited:
                self.on_unsolicited(raw)
            return

        response.purpose = pending.purpose
        pending.response = response
        if pending.multiline:
            with self._lock:
                self._open = (pending, response)
                self._open_deadline = time.time() + 0.3
            return
        self._deliver(pending, response)

    def _take_pending(self, cid):
        with self._lock:
            if cid is not None:
                for pending in self._pending:
                    if pending.id == cid:
                        self._pending.remove(pending)
                        return pending
                return None
            if self._pending:
                return self._pending.pop(0)
            return None

    def _finish_open(self, reason):
        with self._lock:
            opening = self._open
            self._open = None
        if opening is None:
            return
        pending, response = opening
        pending.response = response
        self._deliver(pending, response)

    def _deliver(self, pending, response):
        if self.on_response:
            try:
                self.on_response(response)
            except Exception as exc:                 # keep the reader alive
                self.log("响应处理异常: %s" % exc)
        pending.event.set()

    # ------------------------------------------------------------------ helpers
    def has_pending(self, purpose=None):
        with self._lock:
            if purpose is None:
                return bool(self._pending)
            return any(pending.purpose == purpose for pending in self._pending)

    def pending_age(self, purpose=None):
        with self._lock:
            items = [p for p in self._pending if purpose is None or p.purpose == purpose]
            if not items:
                return 0.0
            return time.time() - min(p.created for p in items)

    def complete_pending(self, purpose, body="", ok=True):
        """Complete a pending command from a bare line (analyze's final ``play``)."""
        with self._lock:
            target = None
            for pending in reversed(self._pending):
                if pending.purpose == purpose:
                    target = pending
                    break
            if target is None:
                return False
            self._pending.remove(target)
        response = GtpResponse(ok=ok, id=target.id, body=body, raw=body, purpose=purpose)
        target.response = response
        self._deliver(target, response)
        return True

    def reset(self, reason="", orphan_skip=False):
        with self._lock:
            dropped = self._pending
            self._pending = []
            self._open = None
            self.streaming = False
            if orphan_skip:
                self._orphan_skip += len(dropped)
        for pending in dropped:
            pending.response = GtpResponse(False, pending.id, "cancelled",
                                           "cancelled", pending.purpose)
            pending.event.set()
        if dropped and reason:
            self.log("%s：丢弃 %d 条未完成命令" % (reason, len(dropped)))

    def close(self):
        self._closed = True
        self.reset("会话关闭")

    # ------------------------------------------------------------------ monitor
    def _monitor_loop(self):
        while not self._closed:
            time.sleep(0.05)
            try:
                with self._lock:
                    opening = self._open
                    deadline = self._open_deadline
                if opening is not None and time.time() >= deadline:
                    self._finish_open("idle")
            except Exception:
                pass
