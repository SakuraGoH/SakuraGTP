import threading
import time

try:
    import paramiko
    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False


class SSHClient:
    """
    内嵌 SSH 客户端：
    - 连接远程主机
    - 执行远程命令（如启动 KataGo）
    - 把远程进程的 stdout/stderr 转发给回调
    - 把输入转发给远程进程 stdin
    """

    def __init__(self, on_output=None, on_error=None, on_exit=None, on_log=None):
        self.on_output = on_output
        self.on_error = on_error
        self.on_exit = on_exit
        self.on_log = on_log

        self.ssh = None
        self.channel = None
        self._running = False
        self._reader_thread = None
        self._lock = threading.Lock()

    def log(self, msg):
        if self.on_log:
            self.on_log(f"[SSH] {msg}")

    def connect(self, host, port, username, password=None, key_file=None, timeout=10):
        """
        连接 SSH 服务器。
        - host: 远程 IP 或域名
        - port: SSH 端口，默认 22
        - username: 用户名
        - password: 密码（可选）
        - key_file: 私钥路径（可选）
        """
        if not HAS_PARAMIKO:
            return False, "未安装 paramiko，请先 pip install paramiko"

        with self._lock:
            if self._running:
                return False, "SSH 已连接"

        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            connect_kwargs = {
                "hostname": host,
                "port": int(port),
                "username": username,
                "timeout": timeout,
            }
            if key_file:
                connect_kwargs["key_filename"] = key_file
            if password:
                connect_kwargs["password"] = password

            ssh.connect(**connect_kwargs)
            self.ssh = ssh
            self._running = True
            self.log(f"已连接 {username}@{host}:{port}")
            return True, "连接成功"
        except Exception as e:
            self.ssh = None
            self._running = False
            return False, f"连接失败: {e}"

    def run_command(self, command):
        """
        在远程执行命令，开启一个持久会话，stdout/stderr 转发给回调。
        - command: 要执行的命令，例如 "./katago gtp -model model.bin.gz -config gtp.cfg"
        """
        if not self._running or not self.ssh:
            return False, "SSH 未连接"

        try:
            transport = self.ssh.get_transport()
            channel = transport.open_session()
            channel.get_pty()
            channel.invoke_shell()
            time.sleep(0.3)
            channel.send(command + "\n")

            self.channel = channel
            self._reader_thread = threading.Thread(
                target=self._read_loop, daemon=True
            )
            self._reader_thread.start()
            self.log(f"已发送命令: {command}")
            return True, "命令已发送"
        except Exception as e:
            return False, f"执行命令失败: {e}"

    def _read_loop(self):
        channel = self.channel
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
                            self.on_output(text)
                else:
                    time.sleep(0.01)
            except Exception:
                break

        self._running = False
        if self.on_exit:
            self.on_exit()

    def send(self, text):
        """把输入发给远程进程 stdin"""
        with self._lock:
            if not self.channel or self.channel.closed:
                return False
            try:
                if not text.endswith("\n"):
                    text += "\n"
                self.channel.send(text.encode("utf-8"))
                return True
            except Exception:
                return False

    def stop(self):
        """断开 SSH"""
        with self._lock:
            self._running = False
            if self.channel:
                try:
                    self.channel.close()
                except Exception:
                    pass
                self.channel = None
            if self.ssh:
                try:
                    self.ssh.close()
                except Exception:
                    pass
                self.ssh = None
        self.log("SSH 已断开")
        return True

    def is_running(self):
        return self._running and self.channel is not None and not self.channel.closed