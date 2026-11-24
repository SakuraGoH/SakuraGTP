# -*- coding: utf-8 -*-
"""time_left 修复的 A/B 验证：用真实 KataGo 测「秒下」是否消失。

用法：
    python tests/manual_timeleft_ab.py

对每个场景开新局，发送与 SakuraGTP 完全相同的命令序列，测量从
``kata-genmove_analyze`` 到最终 ``play`` 行的墙钟时间。

旧：time_left W 0 9   → 引擎认为只剩 0 秒，立刻落子
新：time_left W 9 1   → 引擎认为读秒还有 9 秒
"""

import os
import queue
import subprocess
import sys
import threading
import time

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


class Engine:
    def __init__(self):
        cmd = [KATAGO, "gtp", "-model", MODEL, "-config", CONFIG,
               "-override-config", OVERRIDE]
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="replace", bufsize=1)
        self.q = queue.Queue()
        threading.Thread(target=self._reader, daemon=True).start()
        self.next_id = 0

    def _reader(self):
        for line in self.proc.stdout:
            self.q.put(line.rstrip("\r\n"))

    def send(self, text):
        self.proc.stdin.write(text + "\n")
        self.proc.stdin.flush()

    def wait_ready(self, timeout=180):
        self.send("protocol_version")
        end = time.time() + timeout
        while time.time() < end:
            try:
                line = self.q.get(timeout=1.0)
            except queue.Empty:
                continue
            if line.startswith("="):
                return True
        return False

    def genmove(self, args, timeout=120):
        """发送 time_left + 参数 + genmove_analyze，返回落子耗时（秒）。"""
        self.send("clear_board")
        self.send("boardsize 19")
        self.send("komi 6.5")
        self.send("time_settings 60 9 1")
        self.send("play B Q16")
        self.send("time_left W " + args)
        self.send("kata-set-param maxTime 3.00")
        self.send("kata-set-param maxVisits 100000000")

        start = time.time()
        self.send("kata-genmove_analyze W interval 50 maxmoves 12")
        end = time.time() + timeout
        while time.time() < end:
            try:
                line = self.q.get(timeout=1.0)
            except queue.Empty:
                continue
            if line.startswith("play ") or line.startswith("? "):
                return time.time() - start, line
        return None, "timeout"

    def close(self):
        try:
            self.send("quit")
        except Exception:
            pass
        try:
            self.proc.wait(5)
        except Exception:
            self.proc.kill()


def main():
    if not os.path.exists(KATAGO):
        print("找不到 KataGo:", KATAGO)
        return 1
    eng = Engine()
    try:
        print("KataGo 启动中…")
        if not eng.wait_ready():
            print("KataGo 未就绪")
            return 1
        print("就绪\n")

        cases = [
            ("旧·读秒期 time_left W 0 9", "0 9"),
            ("新·读秒期 time_left W 9 1", "9 1"),
            ("旧·主时间 time_left W 60 9", "60 9"),
            ("新·主时间 time_left W 60 0", "60 0"),
        ]
        for label, args in cases:
            sec, line = eng.genmove(args)
            if sec is None:
                print("%-32s  %s" % (label, line))
            else:
                print("%-32s  %6.3f 秒   落子: %s" % (label, sec, line))
    finally:
        eng.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
