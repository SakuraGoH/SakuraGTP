"""Transport layer for talking to a GTP engine.

Three channels, matching FoxGTP's "通信" menu:

* ``stdio``      – start a local engine as a child process (most common);
* ``tcp-client`` – FoxGTP/we connect to an engine that listens (e.g. ikatago);
* ``tcp-server`` – the engine connects to us (e.g. StandardIOToTcp).

Every transport just moves *lines*: ``start()``, ``send(line)``, ``stop()`` and
two callbacks (``on_line``, ``on_exit``).  Line splitting and decoding happen
here so the session layer only sees clean strings.
"""

import os
import socket
import subprocess
import threading
import time


class Transport:
    kind = "base"

    def __init__(self, on_line=None, on_exit=None):
        self.on_line = on_line
        self.on_exit = on_exit
        self._running = False
        self._lock = threading.RLock()

    # -- API ---------------------------------------------------------------
    def start(self):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError

    def send(self, line):
        raise NotImplementedError

    def is_running(self):
        return self._running

    def describe(self):
        return self.kind

    # -- helpers -----------------------------------------------------------
    def _emit(self, text):
        if self.on_line and text is not None:
            self.on_line(text)

    def _exited(self, reason=""):
        was_running = self._running
        self._running = False
        if was_running and self.on_exit:
            self.on_exit(reason)


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="ignore").rstrip("\r\n")


class StdioTransport(Transport):
    """Run a command and speak GTP over its stdin/stdout."""

    kind = "stdio"

    def __init__(self, command, cwd=None, on_line=None, on_exit=None):
        super().__init__(on_line, on_exit)
        self.command = command or ""
        self.cwd = cwd or None
        self.proc = None
        self._reader = None

    def describe(self):
        return "STDIO: %s" % self.command

    def start(self):
        if not self.command.strip():
            return False, "命令行为空"
        flags = 0
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self.proc = subprocess.Popen(
                self.command,
                shell=True,
                cwd=self.cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=flags,
            )
        except Exception as exc:                     # pragma: no cover - OS level
            self.proc = None
            return False, "启动失败: %s" % exc
        self._running = True
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        return True, "引擎已启动"

    def _read_loop(self):
        proc = self.proc
        if proc is None:
            return
        try:
            while True:
                raw = proc.stdout.readline()
                if not raw:
                    break
                text = _decode(raw)
                if text:
                    self._emit(text)
        except Exception:
            pass
        self._exited("引擎进程结束")

    def send(self, line):
        with self._lock:
            proc = self.proc
            if proc is None or proc.poll() is not None:
                return False
            try:
                proc.stdin.write((line + "\n").encode("utf-8"))
                proc.stdin.flush()
                return True
            except Exception:
                return False

    def stop(self):
        with self._lock:
            self._running = False
            proc = self.proc
            self.proc = None
        if proc is None:
            return
        try:
            if proc.stdin and proc.poll() is None:
                proc.stdin.write(b"quit\n")
                proc.stdin.flush()
        except Exception:
            pass
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            time.sleep(0.05)
        if proc.poll() is None:
            try:
                proc.terminate()
                time.sleep(0.3)
                if proc.poll() is None:
                    proc.kill()
            except Exception:
                pass
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass


class TcpClientTransport(Transport):
    """Connect to an engine that already listens on host:port."""

    kind = "tcp-client"

    def __init__(self, host="127.0.0.1", port=8000, on_line=None, on_exit=None):
        super().__init__(on_line, on_exit)
        self.host = host or "127.0.0.1"
        self.port = int(port or 8000)
        self.sock = None
        self._reader = None
        self._buffer = b""

    def describe(self):
        return "TCP 客户端: %s:%d" % (self.host, self.port)

    def start(self):
        try:
            sock = socket.create_connection((self.host, self.port), timeout=5.0)
            sock.settimeout(None)
        except Exception as exc:
            return False, "连接 AI 引擎失败: %s" % exc
        self.sock = sock
        self._running = True
        self._buffer = b""
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        return True, "已连接 AI 引擎 %s:%d" % (self.host, self.port)

    def _read_loop(self):
        sock = self.sock
        while self._running and sock is not None:
            try:
                data = sock.recv(4096)
            except Exception:
                break
            if not data:
                break
            self._buffer += data
            while b"\n" in self._buffer:
                line, self._buffer = self._buffer.split(b"\n", 1)
                text = _decode(line)
                if text:
                    self._emit(text)
        self._exited("与 AI 引擎的连接断开")

    def send(self, line):
        sock = self.sock
        if sock is None:
            return False
        try:
            sock.sendall((line + "\n").encode("utf-8"))
            return True
        except Exception:
            return False

    def stop(self):
        self._running = False
        sock, self.sock = self.sock, None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                sock.close()
            except Exception:
                pass


class TcpServerTransport(Transport):
    """Listen on host:port and let the engine connect to us."""

    kind = "tcp-server"

    def __init__(self, host="0.0.0.0", port=8000, on_line=None, on_exit=None,
                 on_peer=None):
        super().__init__(on_line, on_exit)
        self.host = host or "0.0.0.0"
        self.port = int(port or 8000)
        self.on_peer = on_peer
        self.server = None
        self.peer = None
        self._accept = None
        self._buffer = b""

    def describe(self):
        return "TCP 服务端: 监听 %s:%d" % (self.host, self.port)

    def has_peer(self):
        return self.peer is not None

    def start(self):
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.host, self.port))
            server.listen(1)
            server.settimeout(0.5)
        except Exception as exc:
            return False, "监听 AI 引擎端口失败: %s" % exc
        self.server = server
        self._running = True
        self._accept = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept.start()
        return True, "等待 AI 引擎连接 %s:%d" % (self.host, self.port)

    def _accept_loop(self):
        while self._running:
            try:
                peer, addr = self.server.accept()
            except socket.timeout:
                continue
            except Exception:
                break
            # 只允许一个引擎连接：新连接顶掉旧的
            old, self.peer = self.peer, peer
            if old is not None:
                try:
                    old.close()
                except Exception:
                    pass
            self._buffer = b""
            if self.on_peer:
                self.on_peer(addr)
            threading.Thread(target=self._read_peer, args=(peer,), daemon=True).start()

    def _read_peer(self, peer):
        while self._running:
            try:
                data = peer.recv(4096)
            except Exception:
                break
            if not data:
                break
            self._buffer += data
            while b"\n" in self._buffer:
                line, self._buffer = self._buffer.split(b"\n", 1)
                text = _decode(line)
                if text:
                    self._emit(text)
        if self.peer is peer:
            self.peer = None
            if self.on_peer:
                self.on_peer(None)
            self._exited("AI 引擎断开连接")

    def send(self, line):
        peer = self.peer
        if peer is None:
            return False
        try:
            peer.sendall((line + "\n").encode("utf-8"))
            return True
        except Exception:
            return False

    def stop(self):
        self._running = False
        server, self.server = self.server, None
        peer, self.peer = self.peer, None
        for sock in (peer, server):
            if sock is None:
                continue
            try:
                sock.close()
            except Exception:
                pass


def build_transport(config, on_line=None, on_exit=None, on_peer=None) -> Transport:
    """Create the transport described by a config mapping.

    ``config["channel"]`` is one of ``stdio`` / ``tcp-client`` / ``tcp-server``.
    """
    channel = (config.get("channel") or "stdio").lower()
    if channel == "tcp-client":
        return TcpClientTransport(
            host=config.get("engine_host", "127.0.0.1"),
            port=config.get("engine_port", 8000),
            on_line=on_line, on_exit=on_exit,
        )
    if channel == "tcp-server":
        return TcpServerTransport(
            host="0.0.0.0",
            port=config.get("engine_port", 8000),
            on_line=on_line, on_exit=on_exit, on_peer=on_peer,
        )
    command = config.get("engine_command") or ""
    return StdioTransport(
        command=command,
        cwd=config.get("working_dir") or None,
        on_line=on_line, on_exit=on_exit,
    )
