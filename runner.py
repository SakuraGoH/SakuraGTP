import subprocess
import threading
import time
import os
import signal


class ContributeRunner:
    def __init__(self, on_log=None):
        self.proc = None
        self.on_log = on_log
        self._running = False
        self._reader_thread = None
        self._lock = threading.Lock()

    def log(self, msg):
        if self.on_log:
            self.on_log(f"[跑谱] {msg}")

    def start(self, command):
        with self._lock:
            if self._running:
                return False, "跑谱已在运行"
            if not command.strip():
                return False, "跑谱命令为空"
            try:
                creationflags = 0
                if os.name == "nt":
                    creationflags = subprocess.CREATE_NO_WINDOW
                self.proc = subprocess.Popen(
                    command,
                    shell=True,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    bufsize=0,
                    creationflags=creationflags,
                )
                self._running = True
                self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
                self._reader_thread.start()
                self.log(f"启动成功: {command}")
                return True, "跑谱启动成功"
            except Exception as e:
                self.proc = None
                self._running = False
                return False, f"跑谱启动失败: {e}"

    def _read_loop(self):
        proc = self.proc
        if not proc:
            return
        buffer = b""
        while self._running and proc.poll() is None:
            try:
                chunk = proc.stdout.read(1)
                if not chunk:
                    time.sleep(0.01)
                    continue
                buffer += chunk
                if chunk == b"\n":
                    text = buffer.decode("utf-8", errors="ignore").rstrip()
                    buffer = b""
                    if text:
                        self.log(text)
            except Exception:
                break
        self._running = False

    def stop(self):
        with self._lock:
            self._running = False
            if self.proc:
                pid = self.proc.pid
                try:
                    if os.name == "nt":
                        # 强制杀掉进程树，包括 cmd.exe 下面挂着的 katago.exe
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(pid)],
                            capture_output=True,
                            creationflags=subprocess.CREATE_NO_WINDOW,
                        )
                    else:
                        os.killpg(os.getpgid(pid), signal.SIGTERM)
                except Exception as e:
                    self.log(f"杀进程失败: {e}")
                self.proc = None
                self.log("跑谱已停止")
        return True

    def is_running(self):
        return self._running and self.proc is not None and self.proc.poll() is None