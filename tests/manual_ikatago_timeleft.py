# -*- coding: utf-8 -*-
"""用真实 iKatago 验证 time_left 修复（需要你自己的 ikatago 账号）。

ikatago-client 本身就是一个 GTP 程序：SakuraGTP 把命令写到它的 stdin、
从它的 stdout 读响应，和 FoxGTP 里的用法完全一样。本脚本用 SakuraGTP
真实的 EngineManager + GTPBridge 驱动它，测量读秒阶段的落子耗时。

用法：
    python tests/manual_ikatago_timeleft.py "<ikatago 命令行>"

示例（Windows，把用户名密码换成你的）：
    python tests/manual_ikatago_timeleft.py ^
      "C:\ikatago\ikatago.exe --platform aistudio --username 你的用户名 --password 你的密码"

如果 ikatago 需要指定权重/配置，也一起写进命令行即可，例如：
    "... --kata-weight 20b --kata-local-config C:\path\gtp.cfg"

输出示例（修复后）：
    主时间 60s        3.05 秒
    读秒期（主时间 0）  3.04 秒
    旧逻辑对照（仅在本脚本内模拟）0.02 秒
"""

import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sakura.engine.manager import EngineManager          # noqa: E402
from sakura.engine.bridge import GTPBridge               # noqa: E402


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
    got = sink.wait_packet(("AFPLAY", "AFSKIP"), 180)
    elapsed = time.time() - start
    if got is None:
        print("%-34s 超时" % label)
    else:
        print("%-34s %6.3f 秒   结果: %s %s" % (label, elapsed, got[0], got[1]))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = " ".join(sys.argv[1:])

    output = []
    mgr = EngineManager(
        on_output=lambda line: (output.append(line), None)[1],
        on_error=lambda line: None,
    )
    ok, msg = mgr.start("", "", "", "", remote_cmd=cmd)
    if not ok:
        print("启动 ikatago 失败:", msg)
        return 1

    sink = FoxSink()
    bridge = GTPBridge(
        engine_manager=mgr,
        send_to_fox=sink.send,
        on_log=lambda line: None,
        on_candidate=lambda c: None,
        on_engine_raw=lambda line: None,
    )
    mgr.on_output = bridge.on_engine_output
    bridge.on_engine_started("ikatago")
    if bridge._probe_thread is not None:
        bridge._probe_thread.join(120)

    print("探测结果: family=%s, time_left=%s\n" % (
        bridge.profile.family, bridge.profile.time_left))
    if not bridge.profile.time_left:
        print("引擎没有声明 time_left，无法做这项验证。")
        bridge.session.stop()
        mgr.stop()
        return 1

    bridge.set_max_time(3.0)
    bridge.max_visits = 0
    bridge.max_playouts = 0

    try:
        one_case(bridge, sink, 60, "主时间 60s")
        one_case(bridge, sink, 0, "读秒期（主时间 0）")

        bridge.dialect.time_left_commands = (
            lambda color, main, byo, count:
            ["time_left %s %d %d" % (color.upper(), max(0, int(main)), int(byo))])
        one_case(bridge, sink, 0, "旧逻辑对照（仅本脚本模拟）")
    finally:
        bridge.session.stop()
        mgr.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
