import socket
import threading
import time

from protocol_fox import parse_packet, build_packet


class FoxClientServer:
    def __init__(self, on_command=None, on_log=None, on_reconnect=None):
        self.on_command = on_command
        self.on_log = on_log
        self.on_reconnect = on_reconnect

        self.server_sock = None
        self.client_sock = None
        self._running = False
        self._thread = None
        self._recv_thread = None
        self._lock = threading.Lock()

        self._port = 6000
        self.auto_reconnect = True
        self.reconnect_interval = 5
        self._reconnect_thread = None

    def log(self, msg):
        if self.on_log:
            self.on_log(msg)

    def start(self, port):
        with self._lock:
            if self._running:
                return False, "已在监听"
            self._port = port
            try:
                self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.server_sock.bind(("0.0.0.0", port))
                self.server_sock.listen(1)
                self._running = True
                self._thread = threading.Thread(target=self._accept_loop, daemon=True)
                self._thread.start()
                self.log(f"开始监听野狐客户端端口 {port}")
                return True, "监听成功"
            except Exception as e:
                self._running = False
                return False, f"监听失败: {e}"

    def _accept_loop(self):
        while self._running:
            try:
                self.server_sock.settimeout(1.0)
                conn, addr = self.server_sock.accept()
                self.client_sock = conn
                self.log(f"野狐客户端已连接: {addr}")
                self._recv_thread = threading.Thread(target=self._recv_loop, args=(conn,), daemon=True)
                self._recv_thread.start()
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    self.log(f"accept 异常: {e}")
                break

    def _recv_loop(self, conn):
        buffer = b""
        while self._running:
            try:
                data = conn.recv(4096)
                if not data:
                    break
                buffer += data
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    text = line.decode("utf-8", errors="ignore").strip()
                    if not text:
                        continue
                    self.log(f"野狐: {text}")
                    parsed = parse_packet(text)
                    if parsed and self.on_command:
                        self.on_command(parsed[0], parsed[1])
            except Exception as e:
                self.log(f"接收异常: {e}")
                break
        self.log("野狐客户端断开")
        with self._lock:
            self.client_sock = None
        if self.auto_reconnect and self._running:
            self._start_reconnect()

    def _start_reconnect(self):
        if self._reconnect_thread and self._reconnect_thread.is_alive():
            return
        self._reconnect_thread = threading.Thread(target=self._reconnect_loop, daemon=True)
        self._reconnect_thread.start()

    def _reconnect_loop(self):
        self.log(f"{self.reconnect_interval} 秒后自动重连...")
        time.sleep(self.reconnect_interval)
        if not self._running:
            return
        self.log("等待野狐客户端重新连接")
        if self.on_reconnect:
            self.on_reconnect()

    def set_auto_reconnect(self, enabled, interval=5):
        self.auto_reconnect = bool(enabled)
        self.reconnect_interval = int(interval)

    def send(self, command, *items):
        with self._lock:
            if not self.client_sock:
                return False
            try:
                packet = build_packet(command, *items)
                self.client_sock.sendall(packet)
                self.log(f"发送: {packet.decode('utf-8', errors='ignore').strip()}")
                return True
            except Exception as e:
                self.log(f"发送失败: {e}")
                return False

    def stop(self):
        with self._lock:
            self._running = False
            self.auto_reconnect = False
            if self.client_sock:
                try:
                    self.client_sock.close()
                except Exception:
                    pass
                self.client_sock = None
            if self.server_sock:
                try:
                    self.server_sock.close()
                except Exception:
                    pass
                self.server_sock = None
        return True

    def is_listening(self):
        return self._running and self.server_sock is not None

    def is_connected(self):
        return self.client_sock is not None
