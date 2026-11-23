"""引擎通信方式测试：stdio 之外的两种 TCP 协议（对齐 FoxGTP 的通信菜单）。"""

import os
import socket
import sys
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine_manager import EngineManager  # noqa: E402


def wait_for(predicate, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class FakeGtpServer:
    """最小 GTP 服务端：收到任何命令都回 ``=<id> ok``。"""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.lines = []
        self.conn = None
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            conn, _addr = self.sock.accept()
            self.conn = conn
            buffer = b""
            while True:
                data = conn.recv(4096)
                if not data:
                    break
                buffer += data
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    text = line.decode("utf-8", "ignore").strip()
                    if not text:
                        continue
                    self.lines.append(text)
                    cid = text.split(" ")[0]
                    conn.sendall(("=%s ok\n\n" % cid).encode())
        except OSError:
            pass

    def close(self):
        for sock in (self.conn, self.sock):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass


class TcpTransportTest(unittest.TestCase):
    def test_tcp_client(self):
        server = FakeGtpServer()
        output = []
        connected = []
        manager = EngineManager(
            on_output=output.append,
            on_connected=lambda: connected.append(True))
        try:
            ok, msg = manager.start_tcp_client("127.0.0.1", server.port)
            self.assertTrue(ok, msg)
            self.assertTrue(manager.is_running())
            self.assertTrue(wait_for(lambda: connected))
            manager.send("1 protocol_version")
            self.assertTrue(wait_for(lambda: any("ok" in line for line in output)))
            self.assertIn("1 protocol_version", server.lines)
        finally:
            manager.stop()
            server.close()
        self.assertFalse(manager.is_running())

    def test_tcp_server(self):
        output = []
        connected = []
        manager = EngineManager(
            on_output=output.append,
            on_connected=lambda: connected.append(True))
        client = None
        try:
            ok, msg = manager.start_tcp_server("127.0.0.1", 0)
            self.assertTrue(ok, msg)
            port = manager._server_sock.getsockname()[1]
            client = socket.create_connection(("127.0.0.1", port), timeout=5)
            self.assertTrue(wait_for(lambda: connected), "引擎接入后应触发 on_connected")
            self.assertTrue(manager.is_running())
            manager.send("1 name")
            client.settimeout(5)
            data = client.recv(4096)
            self.assertIn(b"1 name", data)
        finally:
            if client is not None:
                client.close()
            manager.stop()
        self.assertFalse(manager.is_running())


if __name__ == "__main__":
    unittest.main()
