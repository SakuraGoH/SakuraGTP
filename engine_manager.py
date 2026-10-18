import subprocess
import threading
import time
import os
import signal

try:
    import paramiko
    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False


class EngineManager:
    def __init__(self, on_output=None, on_error=None, on_exit=None):
        self.proc = None
        self.ssh_client = None
        self.on_output = on_output
        self.on_error = on_error
        self.on_exit = on_exit
        self._reader_thread = None
        self._running = False
        self._lock = threading.Lock()
        self._remote_mode = False
        self._ssh_mode = False

        # 心跳
        self.heartbeat_enabled = False
        self.heartbeat_interval = 30
        self.heartbeat_timeout = 10
        self._last_heartbeat_reply = 0
        self._heartbeat_thread = None
        self._heartbeat_cmd_id = 0

    def set_heartbeat(self, enabled, interval=30, timeout=10):
        self.heartbeat_enabled = bool(enabled)
        self.heartbeat_interval = int(interval)
        self.heartbeat_timeout = int(timeout)

    # ---------- 本地 / 远程命令行 ----------
    def build_command(self, engine_path, weight_path, config_path, extra_args=""):
        if not engine_path:
            return ""
        name = os.path.basename(engine_path).lower()
        if "katago" in name:
            parts = [f'"{engine_path}"', "gtp"]
            if weight_path:
                parts.append(f'-model "{weight_path}"')
            if config_path:
                parts.append(f'-config "{config_path}"')
            if extra_args:
                parts.append(extra_args)
            return " ".join(parts)
        else:
            parts = [f'"{engine_path}"', "--gtp", "--quiet", "--noponder"]
            if weight_path:
                parts.append(f'-w "{weight_path}"')
            if config_path:
                parts.append(f'--config "{config_path}"')
            if extra_args:
                parts.append(extra_args)
            return " ".join(parts)

    def start(self, engine_path, weight_path, config_path, extra_args="", remote_cmd=""):
        with self._lock:
            if self._running:
                return False, "引擎已在运行"

            if remote_cmd:
                cmd = remote_cmd.strip()
                self._remote_mode = True
                self._ssh_mode = False
                if "plink" in cmd.lower():
                    if "-batch" not in cmd:
                        cmd = cmd.replace("plink.exe", "plink.exe -batch", 1)
                        cmd = cmd.replace("plink", "plink -batch", 1)
            else:
                cmd = self.build_command(engine_path, weight_path, config_path, extra_args)
                self._remote_mode = False
                self._ssh_mode = False

            if not cmd:
                return False, "引擎路径为空"

            try:
                creationflags = 0
                if os.name == "nt":
                    creationflags = subprocess.CREATE_NO_WINDOW

                self.proc = subprocess.Popen(
                    cmd,
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
                self._start_heartbeat()
                return True, f"启动成功: {cmd}"
            except Exception as e:
                self.proc = None
                self._running = False
                return False, f"启动失败: {e}"

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
                    if text and self.on_output:
                        # 心跳响应检测
                        if "protocol_version" in text or text.strip().startswith("="):
                            self._last_heartbeat_reply = time.time()
                        self.on_output(text)
            except Exception:
                break

        self._running = False
        if self.on_exit:
            self.on_exit()

    # ---------- 心跳 ----------
    def _start_heartbeat(self):
        if not self.heartbeat_enabled:
            return
        self._last_heartbeat_reply = time.time()
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

    def _heartbeat_loop(self):
        while self._running:
            time.sleep(self.heartbeat_interval)
            if not self._running:
                break
            # 发心跳
            self._heartbeat_cmd_id += 1
            cid = self._heartbeat_cmd_id
            hb_cmd = f"{cid} protocol_version"
            try:
                # 先记录到 GTP Shell
                if self.on_output:
                    self.on_output(f">>> [心跳] {hb_cmd}")
                self.send(hb_cmd)
            except Exception:
                pass
            # 等待响应
            time.sleep(self.heartbeat_timeout)
            if not self._running:
                break
            elapsed = time.time() - self._last_heartbeat_reply
            if elapsed > self.heartbeat_timeout + 2:
                # 超过 timeout+2 秒没响应，判定假死
                if self.on_output:
                    self.on_output(f"[心跳] 引擎无响应 {elapsed:.1f} 秒，判定假死")
                if self.on_exit:
                    self.on_exit()
                self.stop()
                break

    # ---------- 内嵌 SSH ----------
    def start_ssh(self, host, port, username, password, key_file, command):
        if not HAS_PARAMIKO:
            return False, "未安装 paramiko，请先 pip install paramiko"

        with self._lock:
            if self._running:
                return False, "引擎已在运行"

        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            kwargs = {
                "hostname": host,
                "port": int(port),
                "username": username,
                "timeout": 10,
            }
            if key_file:
                kwargs["key_filename"] = key_file
            if password:
                kwargs["password"] = password
            ssh.connect(**kwargs)
            self.ssh_client = ssh
        except Exception as e:
            self.ssh_client = None
            return False, f"SSH 连接失败: {e}"

        try:
            transport = ssh.get_transport()
            channel = transport.open_session()
            channel.get_pty()
            channel.invoke_shell()
            time.sleep(0.3)
            channel.send(command + "\n")
        except Exception as e:
            try:
                ssh.close()
            except Exception:
                pass
            self.ssh_client = None
            return False, f"SSH 执行命令失败: {e}"

        self._ssh_channel = channel
        self._running = True
        self._ssh_mode = True
        self._remote_mode = False
        self._reader_thread = threading.Thread(target=self._read_ssh_loop, daemon=True)
        self._reader_thread.start()
        self._start_heartbeat()
        return True, f"SSH 启动成功: {command}"

    def _read_ssh_loop(self):
        channel = self._ssh_channel
        if not channel:
            return
        buffer = b""
        while self._running and not channel.closed:
            try:
                if channel.recv_ready():
                    data = channel.recv(4096)
                    if not data:
                        break
                    buffer += data
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        text = line.decode("utf-8", errors="ignore").rstrip("\r")
                        if text and self.on_output:
                            if "protocol_version" in text or text.strip().startswith("="):
                                self._last_heartbeat_reply = time.time()
                            self.on_output(text)
                else:
                    time.sleep(0.01)
            except Exception:
                break

        self._running = False
        if self.on_exit:
            self.on_exit()

    def send(self, text):
        with self._lock:
            if self._ssh_mode and hasattr(self, "_ssh_channel") and self._ssh_channel:
                try:
                    if not text.endswith("\n"):
                        text += "\n"
                    self._ssh_channel.send(text.encode("utf-8"))
                    return True
                except Exception:
                    return False
            if not self.proc or self.proc.poll() is not None:
                return False
            try:
                if not text.endswith("\n"):
                    text += "\n"
                self.proc.stdin.write(text.encode("utf-8"))
                self.proc.stdin.flush()
                return True
            except Exception:
                return False

    def stop(self):
        with self._lock:
            self._running = False
            if self._ssh_mode:
                if hasattr(self, "_ssh_channel") and self._ssh_channel:
                    try:
                        self._ssh_channel.close()
                    except Exception:
                        pass
                    self._ssh_channel = None
                if self.ssh_client:
                    try:
                        self.ssh_client.close()
                    except Exception:
                        pass
                    self.ssh_client = None
                self._ssh_mode = False
            if self.proc:
                try:
                    if os.name == "nt":
                        self.proc.terminate()
                    else:
                        self.proc.send_signal(signal.SIGTERM)
                    time.sleep(0.3)
                    if self.proc.poll() is None:
                        self.proc.kill()
                except Exception:
                    pass
                self.proc = None
        return True

    def is_running(self):
        if self._ssh_mode and hasattr(self, "_ssh_channel") and self._ssh_channel:
            return self._running and not self._ssh_channel.closed
        return self._running and self.proc is not None and self.proc.poll() is None
