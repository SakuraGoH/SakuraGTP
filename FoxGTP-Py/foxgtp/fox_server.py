"""Wild Fox client server: listens for the Fox Go client and exchanges packets.

FoxGTP is a TCP *server* here: the Fox client connects to it on the configured
port.  Only one client is allowed at a time (a new connection replaces the old
one), which matches FoxGTP's "single connection limit".
"""

import socket
import threading

from .fox_protocol import FoxProtocolError, build_packet, parse_packet


class FoxServer:
    def __init__(self, on_packet=None, on_status=None, on_log=None,
                 on_error=None):
        self.on_packet = on_packet
        self.on_status = on_status        # (connected: bool, text: str)
        self.on_log = on_log              # (direction, text)
        self.on_error = on_error          # (text)

        self._server = None
        self._client = None
        self._running = False
        self._lock = threading.RLock()
        self._thread = None
        self.host = "0.0.0.0"
        self.port = 6000
        self.last_peer = ""

    # ------------------------------------------------------------------ life cycle
    def start(self, host="0.0.0.0", port=6000):
        with self._lock:
            if self._running:
                return False, "已在监听"
            try:
                server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.bind((host, int(port)))
                server.listen(1)
                server.settimeout(0.5)
            except Exception as exc:
                try:
                    server.close()
                except Exception:
                    pass
                return False, "监听野狐客户端失败: %s" % exc
            self._server = server
            self.host = host
            self.port = int(port)
            self._running = True
            self._thread = threading.Thread(target=self._accept_loop, daemon=True)
            self._thread.start()
        self._notify_status(False, "等待野狐客户端连接 %s:%d" % (host, port))
        return True, "开始监听野狐客户端 %d" % int(port)

    def stop(self):
        with self._lock:
            self._running = False
            server, self._server = self._server, None
            client, self._client = self._client, None
        for sock in (client, server):
            if sock is None:
                continue
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                sock.close()
            except Exception:
                pass
        if client is not None:
            self._notify_status(False, "已停止监听野狐客户端")

    def is_listening(self):
        return self._running and self._server is not None

    def is_connected(self):
        return self._client is not None

    # ------------------------------------------------------------------ accept / read
    def _accept_loop(self):
        while self._running:
            try:
                client, address = self._server.accept()
            except socket.timeout:
                continue
            except Exception:
                break
            with self._lock:
                old = self._client
                self._client = client
                self.last_peer = "%s:%d" % (address[0], address[1])
            if old is not None:
                try:
                    old.close()
                except Exception:
                    pass
                if self.on_log:
                    self.on_log("info", "检测到新的野狐连接，已断开旧连接")
            self._enable_keepalive(client)
            self._notify_status(True, "野狐客户端已连接: %s" % self.last_peer)
            threading.Thread(target=self._read_loop, args=(client,), daemon=True).start()

    @staticmethod
    def _enable_keepalive(sock):
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            if hasattr(socket, "SIO_KEEPALIVE_VALS"):
                sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 10000, 3000))
        except Exception:
            pass

    def _read_loop(self, client):
        buffer = b""
        while self._running:
            try:
                data = client.recv(4096)
            except Exception:
                break
            if not data:
                break
            buffer += data
            while b"\n" in buffer:
                raw, buffer = buffer.split(b"\n", 1)
                text = raw.decode("utf-8", errors="ignore").strip()
                if not text:
                    continue
                if self.on_log:
                    self.on_log("in", text)
                try:
                    packet = parse_packet(text)
                except FoxProtocolError as exc:
                    if self.on_error:
                        self.on_error("野狐协议包解析失败: %s（%s）" % (text, exc))
                    continue
                if self.on_packet:
                    try:
                        self.on_packet(packet)
                    except Exception as exc:            # keep the reader alive
                        if self.on_error:
                            self.on_error("处理野狐命令异常: %s" % exc)
        with self._lock:
            if self._client is client:
                self._client = None
        try:
            client.close()
        except Exception:
            pass
        self._notify_status(False, "野狐客户端断开")

    # ------------------------------------------------------------------ send
    def send(self, command, *items):
        packet = build_packet(command, *items)
        with self._lock:
            client = self._client
        if client is None:
            return False
        try:
            client.sendall(packet)
        except Exception:
            return False
        if self.on_log:
            self.on_log("out", packet.decode("utf-8", errors="ignore").strip())
        return True

    def _notify_status(self, connected, text):
        if self.on_status:
            try:
                self.on_status(connected, text)
            except Exception:
                pass
