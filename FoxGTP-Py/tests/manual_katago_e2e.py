"""End-to-end test with a REAL engine and a real TCP Fox client.

Not part of the unit suite (needs a KataGo/Leela binary).  Run manually:

    set KATAGO_EXE=...\\katago.exe
    set KATAGO_MODEL=...\\model.onnx
    set KATAGO_CFG=...\\gtp.cfg
    python tests\\manual_katago_e2e.py
"""

import os
import socket
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from foxgtp.config import DEFAULT_CONFIG
from foxgtp.controller import Controller
from foxgtp.fox_protocol import build_packet, parse_packet

EXE = os.environ.get("KATAGO_EXE", r"C:\KataGo\katago.exe")
MODEL = os.environ.get("KATAGO_MODEL", r"C:\KataGo\model.onnx")
CFG = os.environ.get("KATAGO_CFG", r"C:\KataGo\gtp.cfg")
PORT = int(os.environ.get("FOX_TEST_PORT", "6123"))


def wait_for(predicate, timeout, label=""):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.1)
    print("TIMEOUT waiting for", label)
    return False


class FoxClient:
    def __init__(self, port):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.sock.settimeout(0.2)
        self.buffer = b""
        self.packets = []

    def send(self, command, *items):
        self.sock.sendall(build_packet(command, *items))

    def poll(self, timeout=0.5):
        end = time.time() + timeout
        while time.time() < end:
            try:
                data = self.sock.recv(4096)
            except socket.timeout:
                continue
            except Exception:
                break
            if not data:
                break
            self.buffer += data
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            text = line.decode("utf-8", "ignore").strip()
            if text:
                try:
                    packet = parse_packet(text)
                except Exception as exc:
                    print("bad packet", text, exc)
                    continue
                self.packets.append(packet)
                print("FOX <----", text)

    def first(self, command):
        for packet in self.packets:
            if packet.command == command:
                return packet
        return None

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


def main():
    workdir = os.path.join(ROOT, "_run")
    os.makedirs(os.path.join(workdir, "gtp_logs"), exist_ok=True)
    os.makedirs(os.path.join(workdir, "katago_ov_cache"), exist_ok=True)

    config = dict(DEFAULT_CONFIG)
    config.update({
        "channel": "stdio",
        "engine_path": EXE,
        "engine_args": 'gtp -model "%s" -config "%s" -override-config '
                       'onnxProvider=cpu,numSearchThreads=4,nnMaxBatchSize=2'
                       % (MODEL, CFG),
        "working_dir": workdir,
        "fox_port": PORT,
        "save_log": True,
        "log_dir": os.path.join(workdir, "logs"),
        "use_analyze": True,
        "max_time": 3.0,
        "engine_ready_timeout": 180,
    })

    controller = Controller(config, listener=lambda topic, data: None)
    controller.apply_config(config)

    print("=== start engine ===")
    ok, message = controller.start_engine()
    print(message)
    if not ok:
        return 1
    if not wait_for(lambda: controller._engine_ready, 180, "engine ready"):
        return 2
    print("profile:", controller.profile.summary())

    print("=== start fox server ===")
    ok, message = controller.start_fox()
    print(message)
    if not ok:
        return 3
    time.sleep(0.3)

    client = FoxClient(PORT)
    time.sleep(0.3)

    print("=== FARULE ===")
    client.send("FARULE", 19, 60, 30, 5, 650)
    time.sleep(0.5)
    client.poll(0.5)

    print("=== FAMOVE (opponent, AI to move) ===")
    client.send("FAMOVE", 1, "B", "1^3^3^W")
    client.poll(8.0)
    play = client.first("AFPLAY")
    print("AFPLAY:", play)
    if play is None:
        return 4

    print("=== echo AI move ===")
    ai_move = play.items[1]
    client.send("FAMOVE", 0, "B", ai_move)
    time.sleep(0.4)

    print("=== FASCORE ===")
    client.send("FASCORE", 0)
    client.poll(90.0)
    score = client.first("AFSCORE")
    print("AFSCORE:", score)

    print("=== FASKIP (opponent passes) ===")
    client.send("FASKIP", 1, "B")
    client.poll(12.0)
    print("AFPLAY after pass:", client.first("AFPLAY"))

    print("=== status ===")
    print(controller.status())

    client.close()
    controller.stop_fox()
    controller.shutdown()
    print("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
