"""真实引擎冒烟测试：用本机 KataGo（ONNX 构建）走一遍完整链路。

用法（工作目录必须可写，KataGo 的 OpenVINO 后端会在其中建缓存/日志目录）：
    set KATAGO_EXE=...\\katago.exe
    set KATAGO_MODEL=...\\model.onnx
    set KATAGO_CFG=...\\gtp.cfg
    cd _re\\kgtest
    python ..\\smoke_katago.py
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from engine_manager import EngineManager
from gtp_bridge import GTPBridge

# 本机绝对路径用环境变量传，仓库里只留占位默认值
EXE = os.environ.get("KATAGO_EXE", r"C:\KataGo\katago.exe")
MODEL = os.environ.get("KATAGO_MODEL", r"C:\KataGo\model.onnx")
CFG = os.environ.get("KATAGO_CFG", r"C:\KataGo\gtp.cfg")


class Sink:
    def __init__(self):
        self.packets = []

    def __call__(self, command, *items):
        self.packets.append((command, items))
        return True


def main():
    logs = []
    sink = Sink()
    engine = EngineManager(on_output=None, on_exit=lambda: None)
    bridge = GTPBridge(
        engine_manager=engine,
        send_to_fox=sink,
        on_log=lambda m: (logs.append(m), print("[log]", m, flush=True))[1],
        on_candidate=lambda c: None,
        on_engine_raw=lambda line: None,
    )
    engine.on_output = bridge.on_engine_output

    # 这台机器没有 Intel GPU/NPU，配置里的 OpenVINO GPU/NPU 会卡住，强制走 CPU
    extra = "-override-config onnxProvider=cpu,numSearchThreads=4,nnMaxBatchSize=2"
    ok, msg = engine.start(EXE, MODEL, CFG, extra)
    print("[start]", ok, msg)
    if not ok:
        return 1
    bridge.on_engine_started(EXE)

    # 等探测完成（KataGo 加载 ONNX 权重可能要几十秒）
    for _ in range(360):
        if bridge._ready:
            break
        time.sleep(0.5)
    print("[probe] ready =", bridge._ready, "|", bridge.profile.summary())

    # 开局
    bridge.handle_fox_command("FARULE", ["19", "60", "30", "5", "650"])
    bridge.handle_fox_command("FAMOVE", ["0", "B", "1^3^3^W"])
    print("[sync] moves =", bridge._events, "| engine =", bridge._engine_events)

    # 轮到 AI
    t0 = time.time()
    bridge.handle_fox_command("FAMOVE", ["1", "B", "1^3^3^W"])
    for _ in range(240):
        if sink.packets:
            break
        time.sleep(0.5)
    print("[genmove] %.1fs" % (time.time() - t0), sink.packets)
    print("[candidates]", len(bridge._candidates), list(bridge._candidates)[:6])
    if bridge._candidates:
        sample = list(bridge._candidates.values())[0]
        print("[candidate sample]", {k: sample[k] for k in ("vertex", "visits", "winrate", "score")})

    # 回显 AI 的手，再来一手对手棋（模拟野狐继续）
    if sink.packets and sink.packets[-1][0] == "AFPLAY":
        move = sink.packets[-1][1][1]
        n, x, y, c = move.split("^")
        bridge.handle_fox_command("FAMOVE", ["0", "B", move])
        bridge.handle_fox_command("FAMOVE", ["1", "B", "%d^%d^%d^W" % (int(n) + 1, 15, 3)])
        for _ in range(240):
            if len(sink.packets) >= 2:
                break
            time.sleep(0.5)
        print("[genmove2]", sink.packets)

    # 点目
    if os.environ.get("SKIP_SCORE") == "1":
        print("[score] skipped")
    else:
        t0 = time.time()
        bridge.handle_fox_command("FASCORE", ["0"])
        for _ in range(240):
            if any(p[0] == "AFSCORE" for p in sink.packets):
                break
            time.sleep(0.5)
        print("[score] %.1fs" % (time.time() - t0),
              [p for p in sink.packets if p[0] == "AFSCORE"])

    # 重连：给一份不相符的棋谱，看是否整盘重建
    bridge.handle_fox_command(
        "FASTATUS", ["1", "B", "1^15^15^W", "2^3^3^B", "3^15^3^W"])
    time.sleep(1.0)
    print("[rebuild] events =", bridge._events, "| engine =", bridge._engine_events)

    bridge.on_engine_stopped()
    engine.stop()
    print("[done] total packets:", len(sink.packets))
    return 0


if __name__ == "__main__":
    sys.exit(main())
