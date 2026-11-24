# -*- coding: utf-8 -*-
"""端到端验证：真实 KataGo + TCP 中转（与 iKatago 同构）+ SakuraGTP 桥接层。

iKatago 在本机上就是一个「TCP 端口 ↔ 远端 KataGo」的 GTP 中转；这里用
本地 stdio↔TCP 中转模拟同一条链路，验证修复前后的落子耗时。

用法：
    python tests/manual_tcp_timeleft_e2e.py
"""

import os
import socket
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sakura.engine.manager import EngineManager          # noqa: E402
from sakura.engine.bridge import GTPBridge               # noqa: E402

KATAGO = r"C:\Users\10632\Desktop\KataGo\cpp\build\Release\katago.exe"
MODEL = r"C:\Users\10632\Desktop\KataGo\cpp\build\Release\b20.bin"
CONFIG = r"C:\Users\10632\Desktop\KataGo\cpp\build\Release\gtp.cfg"

OVERRIDE = ",".join([
    "logAllGTPCommunication=false",
    "logSearchInfo=false",
    "logToStderr=false",
    "ponderingEnabled=false",
    "maxTime=3.0",
    "maxVisits=100000000",
    "lagBuffer=1.0",
])


def start_relay():
    """起一个 TCP 端口，把收到的数据转发给本地 KataGo（iKatago 的最小同构）。"""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def run():
        conn, _addr = srv.accept()
        proc = subprocess.Popen(
            [KATAGO, "gtp", "-model", MODEL, "-config", CONFIG,
             "-override-config", OVERRIDE],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
            errors="replace", bufsize=1)

        def engine_to_tcp():
            try:
                for line in proc.stdout:
                    conn.sendall(line.encode("utf-8"))
            except OSError:
                pass

        threading.Thread(target=engine_to_tcp, daemon=True).start()
        try:
            while True:
                data = conn.recv(65536)
                if not data:
                    break
                proc.stdin.write(data.decode("utf-8", "replace"))
                proc.stdin.flush()
        except OSError:
            pass
        finally:
            try:
                proc.stdin.write("quit\n")
                proc.stdin.flush()
            except Exception:
                pass
            try:
                proc.wait(5)
            except Exception:
                proc.kill()
            conn.close()

    threading.Thread(target=run, daemon=True).start()
    return port


class FoxSink:
    def __init__(self):
        self.packets = []
        self.lock = threading.Lock()

    def send(self, command, *items):
        with self.lock:
            self.packets.append((command, tuple(items), time.time()))
        return True

    def wait_packet(self, names, timeout):
        end = time.time() + timeout
        while time.time() < end:
            with self.lock:
                for cmd, items, ts in self.packets:
                    if cmd in names:
                        return cmd, items, ts
            time.sleep(0.01)
        return None


def one_case(bridge, sink, main_left, label):
    bridge.handle_fox_command("FARULE", ["19", "60", "9", "5", "650"])
    bridge.handle_fox_command("FASTATUS", ["1", "W"])
    bridge.handle_fox_command("FATIMELEFT", [str(main_left), "9", "5"])

    with sink.lock:
        sink.packets.clear()
    start = time.time()
    bridge.handle_fox_command("FAMOVE", ["1", "W", "1^15^3^B"])
    got = sink.wait_packet(("AFPLAY", "AFSKIP"), 120)
    elapsed = time.time() - start
    if got is None:
        print("%-34s 超时" % label)
    else:
        print("%-34s %6.3f 秒   结果: %s %s" % (label, elapsed, got[0], got[1]))
    return elapsed


def main():
    port = start_relay()
    connected = threading.Event()
    output = []

    mgr = EngineManager(
        on_output=lambda line: output.append(line),
        on_connected=lambda: connected.set(),
    )
    ok, msg = mgr.start_tcp_client("127.0.0.1", port)
    if not ok:
        print("连接失败:", msg)
        return 1
    connected.wait(10)

    sink = FoxSink()
    bridge = GTPBridge(
        engine_manager=mgr,
        send_to_fox=sink.send,
        on_log=lambda line: None,
        on_candidate=lambda c: None,
        on_engine_raw=lambda line: None,
    )
    mgr.on_output = bridge.on_engine_output
    bridge.on_engine_started("katago")
    if bridge._probe_thread is not None:
        bridge._probe_thread.join(60)
    print("探测结果: family=%s, time_left=%s\n" % (
        bridge.profile.family, bridge.profile.time_left))

    bridge.set_max_time(3.0)
    bridge.max_visits = 0        # → kata-set-param maxVisits 100000000
    bridge.max_playouts = 0

    try:
        one_case(bridge, sink, 60, "新代码·主时间 60s")
        one_case(bridge, sink, 0, "新代码·读秒期（主时间 0）")

        # 换回旧实现，复现「秒下」
        bridge.dialect.time_left_commands = (
            lambda color, main, byo, count:
            ["time_left %s %d %d" % (color.upper(), max(0, int(main)), int(byo))])
        one_case(bridge, sink, 0, "旧代码·读秒期（主时间 0）")
    finally:
        bridge.session.stop()
        mgr.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
