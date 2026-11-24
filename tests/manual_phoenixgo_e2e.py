"""PhoenixGo 兼容性手动测试（真实引擎，不参与 unittest）。

默认使用本机的 PhoenixGo + KataGo 权重配置；可用环境变量覆盖命令：

    set PHOENIXGO_CMD="C:/.../mcts_main.exe" --config_path="C:/.../mcts_onnx_katago.conf" --gtp --logtostderr

验证点：
1. 能力探测识别为 PhoenixGo，不走 KataGo 分支；
2. 开局只发核心 GTP（不得出现 kata-*）；
3. 对手落子后 genmove，能正常回 $AFPLAY；
4. final_score 结果按野狐格式回 $AFSCORE；
5. 贴目非 7.5 时引擎会拒绝，程序给出明确提示。

用法：python tests\\manual_phoenixgo_e2e.py
"""

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sakura.engine.manager import EngineManager  # noqa: E402
from sakura.engine.bridge import GTPBridge  # noqa: E402

DEFAULT_CMD = (
    r'"C:/Users/10632/Desktop/PhoenixGo/PhoenixGo-master/out/Release/mcts_main.exe" '
    r'--config_path="C:/Users/10632/Desktop/PhoenixGo/PhoenixGo-master/etc/mcts_onnx_katago.conf" '
    r'--gtp --logtostderr'
)


def wait_for(predicate, timeout, label=""):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.1)
    print("TIMEOUT:", label)
    return False


def main():
    cmd = os.environ.get("PHOENIXGO_CMD", DEFAULT_CMD)
    logs = []
    packets = []
    engine = EngineManager(on_output=None)
    bridge = GTPBridge(
        engine,
        send_to_fox=lambda *a: packets.append(a),
        on_log=lambda m: (logs.append(m), print("LOG", m, flush=True)),
    )
    engine.on_output = bridge.on_engine_output
    failed = []

    def check(cond, label):
        print(("PASS  " if cond else "FAIL  ") + label, flush=True)
        if not cond:
            failed.append(label)

    try:
        ok, msg = engine.start("", "", "", "", remote_cmd=cmd)
        check(ok, "引擎启动: %s" % msg)
        if not ok:
            return 2
        bridge.on_engine_started(cmd)
        if not wait_for(lambda: bridge._ready, 180, "engine ready"):
            return 3

        print("profile:", bridge.profile.summary(), flush=True)
        check(bridge.profile.family == "phoenixgo", "识别为 PhoenixGo")
        check(not bridge.profile.kata, "不走 KataGo 命令分支")

        bridge.handle_fox_command("FARULE", ["19", "600", "30", "5", "750"])
        moves = ["%d^%d^%d^%s" % (i, (i - 1) // 19, (i - 1) % 19,
                                  "B" if i % 2 else "W") for i in range(1, 21)]
        bridge.handle_fox_command("FASTATUS", ["1", "B"] + moves)
        bridge.handle_fox_command("FAMOVE", ["1", "W", "21^1^1^W"])

        check(wait_for(lambda: any(p[0] == "AFPLAY" for p in packets), 90, "AFPLAY"),
              "genmove 返回落子（$AFPLAY）")
        bridge.handle_fox_command("FASCORE", ["0"])
        check(wait_for(lambda: any(p[0] == "AFSCORE" for p in packets), 30, "AFSCORE"),
              "final_score 正常回 $AFSCORE")

        bridge.handle_fox_command("FARESULT", ["W+350"])
        time.sleep(0.5)
        sent = [c for c in logs if c.startswith("GTP发送: ")]
        check(not any("kata-" in c for c in sent), "全程没有发送 kata-* 命令")

        bridge.handle_fox_command("FARULE", ["19", "600", "30", "5", "650"])
        time.sleep(1.5)
        check(any("贴目" in c and "7.5" in c for c in logs),
              "非常规贴目被拒绝时给出提示")
    finally:
        engine.stop()

    print("\n结果: %s" % ("全部通过" if not failed else "失败 %d 项: %s" % (len(failed), failed)),
          flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
