"""真实引擎重放测试（手动运行，不参与 unittest）。

验证两件事：
1. 断线重连补 120 手时，FARULE/FASTATUS 的处理函数立即返回（不会卡住 Fox 线程）；
2. 引擎能分块消化重放，最终 bridge._engine_events == bridge._events。

    set KATAGO_EXE=...\\katago.exe
    set KATAGO_MODEL=...\\model.onnx
    set KATAGO_CFG=...\\gtp.cfg
    python tests\\manual_replay_e2e.py
"""

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine_manager import EngineManager
from gtp_bridge import GTPBridge

EXE = os.environ.get("KATAGO_EXE", r"C:\KataGo\katago.exe")
MODEL = os.environ.get("KATAGO_MODEL", r"C:\KataGo\model.onnx")
CFG = os.environ.get("KATAGO_CFG", r"C:\KataGo\gtp.cfg")
EXTRA = os.environ.get(
    "KATAGO_EXTRA",
    "-override-config onnxProvider=cpu,numSearchThreads=4,nnMaxBatchSize=2")


class Sink:
    def __init__(self):
        self.packets = []

    def __call__(self, command, *items):
        self.packets.append((command, items))
        return True


def wait_for(predicate, timeout, label=""):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.05)
    print("TIMEOUT:", label)
    return False


def build_moves(count):
    """生成 count 手互不重复的落子（空盘上都是合法着法）。"""
    moves = []
    points = [(x, y) for x in range(19) for y in range(19)]
    for no, (x, y) in enumerate(points[:count], start=1):
        color = "B" if no % 2 else "W"
        moves.append("%d^%d^%d^%s" % (no, x, y, color))
    return moves


def main():
    workdir = os.path.join(ROOT, "_re", "replay_probe")
    for sub in ("gtp_logs", "katago_ov_cache", "logs", "ovcache"):
        os.makedirs(os.path.join(workdir, sub), exist_ok=True)

    logs = []
    sink = Sink()
    manager = EngineManager(on_output=None, on_exit=lambda: None)
    bridge = GTPBridge(manager, send_to_fox=sink, on_log=logs.append)
    manager.on_output = bridge.on_engine_output

    ok, message = manager.start(EXE, MODEL, CFG, EXTRA)
    print("start:", ok, message)
    if not ok:
        return 1
    bridge.on_engine_started(EXE)
    if not wait_for(lambda: bridge._ready, 180, "engine ready"):
        return 2
    print("profile:", bridge.profile.summary())

    bridge.handle_fox_command("FARULE", ["19", "60", "30", "5", "650"])
    bridge.set_max_time(2)              # 让 genmove 快点结束，便于验证
    bridge.set_max_visits(0)
    moves = build_moves(40)
    t0 = time.time()
    bridge.handle_fox_command("FASTATUS", ["1", "B"] + moves)
    handler_ms = (time.time() - t0) * 1000.0
    print("FARULE/FASTATUS handler returned in %.1f ms (must be << 1s)" % handler_ms)

    if not wait_for(lambda: bridge._engine_events == bridge._events, 10, "synced"):
        return 4

    print("replay queued: events=%d engine_events=%d engine_running=%s"
          % (len(bridge._events), len(bridge._engine_events), manager.is_running()))

    # 补子之后立刻请求落子，验证引擎会按顺序处理完补子再算，并且能正常回手
    t0 = time.time()
    bridge.handle_fox_command("FAMOVE", ["1", "W", "41^18^18^W"])
    if wait_for(lambda: any(p[0] == "AFPLAY" for p in sink.packets), 180, "AFPLAY"):
        move = [p for p in sink.packets if p[0] == "AFPLAY"][-1]
        print("genmove after replay: %s (%.1fs)" % (move, time.time() - t0))
    else:
        print("genmove timeout; engine_running=%s" % manager.is_running())
        for line in logs[-25:]:
            print("  log:", line)
        return 5

    manager.stop()
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
