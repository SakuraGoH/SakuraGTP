"""Manual GUI end-to-end test: real KataGo + real TCP Fox client + real windows.

    set KATAGO_EXE=...\\katago.exe
    set KATAGO_MODEL=...\\model.onnx
    set KATAGO_CFG=...\\gtp.cfg
    python tests\\manual_gui_e2e.py
"""

import os
import socket
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PyQt5.QtWidgets import QApplication

from app import theme
from app.ui_main import MainWindow
from foxgtp.fox_protocol import build_packet, parse_packet

EXE = os.environ.get("KATAGO_EXE", r"C:\KataGo\katago.exe")
MODEL = os.environ.get("KATAGO_MODEL", r"C:\KataGo\model.onnx")
CFG = os.environ.get("KATAGO_CFG", r"C:\KataGo\gtp.cfg")
PORT = int(os.environ.get("FOX_TEST_PORT", "6124"))


def pump(app, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def main():
    workdir = os.path.join(ROOT, "_run")
    os.makedirs(os.path.join(workdir, "gtp_logs"), exist_ok=True)
    os.makedirs(os.path.join(workdir, "katago_ov_cache"), exist_ok=True)

    app = QApplication(sys.argv)
    theme.apply_theme(app)
    window = MainWindow()
    window.resize(1500, 900)
    window.show()
    pump(app, 0.5)

    # configure engine in the UI fields
    window.channel_combo.setCurrentIndex(0)
    window.engine_path_edit.setText(EXE)
    window.engine_args_edit.setText(
        'gtp -model "%s" -config "%s" -override-config '
        'onnxProvider=cpu,numSearchThreads=4,nnMaxBatchSize=2' % (MODEL, CFG))
    window.fox_port_spin.setValue(PORT)
    window.config["working_dir"] = workdir
    window.config["engine_ready_timeout"] = 180
    window.config["max_time"] = 3.0
    pump(app, 0.2)

    print("== click Connect ==")
    window._connect_engine()
    deadline = time.time() + 180
    while time.time() < deadline and not window.controller._engine_ready:
        pump(app, 0.2)
    print("ready:", window.controller._engine_ready,
          "|", window.controller.profile.summary())
    pump(app, 0.5)
    window.grab().save(os.path.join(ROOT, "gui_connected.png"))

    print("== start listening ==")
    window._start_fox()
    pump(app, 0.3)

    client = socket.create_connection(("127.0.0.1", PORT), timeout=5)
    client.settimeout(0.5)
    pump(app, 0.3)

    client.sendall(build_packet("FARULE", 19, 60, 30, 5, 650))
    pump(app, 0.4)
    client.sendall(build_packet("FAMOVE", 1, "B", "1^3^3^W"))
    print("waiting for AI move ...")
    move_packet = None
    deadline = time.time() + 120
    buffer = b""
    while time.time() < deadline and move_packet is None:
        pump(app, 0.1)
        try:
            data = client.recv(4096)
        except socket.timeout:
            continue
        buffer += data
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            text = line.decode("utf-8", "ignore").strip()
            if not text:
                continue
            packet = parse_packet(text)
            print("FOX <----", text)
            if packet.command == "AFPLAY":
                move_packet = packet
    print("AFPLAY:", move_packet)
    pump(app, 0.5)

    # show the AI board window with real data
    window._show_ai_board()
    window.ai_board_window.resize(700, 840)
    pump(app, 0.6)
    window.ai_board_window.grab().save(os.path.join(ROOT, "gui_board.png"))
    window.grab().save(os.path.join(ROOT, "gui_connected.png"))

    client.close()
    window.controller.stop_fox()
    window.controller.shutdown()
    pump(app, 0.3)
    print("== done ==")
    return 0 if move_packet else 1


if __name__ == "__main__":
    sys.exit(main())
