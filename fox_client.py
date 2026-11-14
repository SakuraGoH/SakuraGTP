import socket
import sys
import threading
import time

from protocol_fox import parse_packet, build_packet


def _enable_keepalive(sock, idle=10, interval=3, count=5):
    """尽量开启 TCP keepalive，快速发现半死连接。任何失败都静默忽略。"""
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except OSError:
        return
    try:
        if sys.platform.startswith("win"):
            # SIO_KEEPALIVE_VALS 需要 (on/off, idle(ms), interval(ms)) 三元组
            sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, idle * 1000, interval * 1000))
        else:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, idle)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, interval)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, count)
    except Exception:
        pass


class FoxClientServer:
    """
    野狐围棋客户端 TCP 监听服务器。

    接收客户端连接，按行解析野狐协议包（protocol_fox），
    通过 on_command(command, items) 上抛；断开后按配置自动等待重连。
    """

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
                if self.server_sock:
                    try:
                        self.server_sock.close()
                    except OSError:
                        pass
                    self.server_sock = None
                return False, f"监听失败: {e}"

    def _accept_loop(self):
        while self._running:
            try:
                self.server_sock.settimeout(1.0)
                conn, addr = self.server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            except Exception as e:
                if self._running:
                    self.log(f"accept 异常: {e}")
                break

            with self._lock:
                old = self.client_sock
                self.client_sock = conn
            if old:
                # 新的客户端已接入，断开旧连接，避免幽灵连接占着状态
                try:
                    old.close()
                except OSError:
                    pass
                self.log("检测到新客户端接入，已断开旧连接")

            _enable_keepalive(conn)
            self.log(f"野狐客户端已连接: {addr}")
            self._recv_thread = threading.Thread(target=self._recv_loop, args=(conn,), daemon=True)
            self._recv_thread.start()

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
            except ConnectionResetError:
                break
            except OSError:
                break
            except Exception as e:
                self.log(f"接收异常: {e}")
                break

        self.log("野狐客户端断开")
        with self._lock:
            if self.client_sock is conn:
                self.client_sock = None
        try:
            conn.close()
        except OSError:
            pass
        if self.auto_reconnect and self._running:
            self._start_reconnect()

    def _start_reconnect(self):
        with self._lock:
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
            if self.client_sock:
                try:
                    self.client_sock.close()
                except OSError:
                    pass
                self.client_sock = None
            if self.server_sock:
                try:
                    self.server_sock.close()
                except OSError:
                    pass
                self.server_sock = None
        return True

    def is_listening(self):
        return self._running and self.server_sock is not None

    def is_connected(self):
        return self.client_sock is not None
