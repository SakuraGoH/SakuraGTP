import os
import queue
import signal
import socket
import subprocess
import threading
import time

try:
    import paramiko
    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False


class EngineManager:
    """
    AI 引擎进程管理器。

    支持三种启动方式：
    - 本地引擎（自动拼命令行或用户自定义命令行 / plink）
    - 内嵌 SSH（paramiko 连远程主机执行命令）
    统一通过 on_output 行回调输出，支持 GTP 心跳假死检测。
    """

    def __init__(self, on_output=None, on_error=None, on_exit=None,
                 on_connected=None, on_disconnected=None):
        self.proc = None
        self.ssh_client = None
        self._ssh_channel = None
        self.on_output = on_output
        self.on_error = on_error
        self.on_exit = on_exit
        self.on_connected = on_connected
        self.on_disconnected = on_disconnected
        self._reader_thread = None
        self._running = False
        self._lock = threading.Lock()
        self._remote_mode = False
        self._ssh_mode = False

        # ---- 连接方式：stdio（本地进程）/ tcp-client / tcp-server / ssh ----
        self._mode = "stdio"
        self._sock = None             # TCP 引擎连接
        self._server_sock = None      # tcp-server 监听
        self._tcp_host = ""
        self._tcp_port = 0
        self._auto_reconnect = True
        self._reconnect_interval = 5
        self._reconnect_thread = None
        self._reconnect_gen = 0

        # 引擎写队列：send() 只入队，真正写 stdin 在独立线程里做。
        # 这样断线重连时一次补几百手也不会把 Fox 读线程卡在管道写满上，
        # 命令顺序与 FoxGTP 一致（先全部 play，随后立刻 genmove）。
        self._write_queue = queue.Queue()
        self._writer_thread = None
        # 写线程的代际：stop/重启时自增，旧线程据此自行退出
        self._writer_gen = 0

    def force_reconnect(self):
        """心跳判定假死时由桥接层调用：TCP 模式下直接触发重连。"""
        if self._mode.startswith("tcp") and self._sock is not None:
            self._socket_lost()
            return True
        return False

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
                    creationflags=creationflags,
                )
                self._running = True
                self._mode = "stdio"
                self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
                self._reader_thread.start()
                self._start_writer()
                return True, f"启动成功: {cmd}"
            except Exception as e:
                self.proc = None
                self._running = False
                return False, f"启动失败: {e}"

    def _read_loop(self):
        proc = self.proc
        if not proc:
            return
        try:
            while self._running:
                line = proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="ignore").rstrip()
                if text and self.on_output:
                    self.on_output(text)
        except Exception:
            pass

        self._running = False
        if self.on_exit:
            self.on_exit()

    # ---------- TCP 引擎（FoxGTP 的另外两种通信方式） ----------
    def start_tcp_client(self, host, port):
        """连接一个已经在监听端口的 GTP 引擎（如 ikatago / 各类 TCP 转发）。"""
        with self._lock:
            if self._running:
                return False, "引擎已在运行"
        try:
            sock = socket.create_connection((host, int(port)), timeout=5)
            sock.settimeout(None)
        except Exception as exc:
            return False, f"连接 {host}:{port} 失败: {exc}"
        self._tcp_host, self._tcp_port = host, int(port)
        self._mode = "tcp-client"
        self._remote_mode = True
        self._ssh_mode = False
        self._sock = sock
        self._running = True
        self._spawn_reader(sock)
        self._start_writer()
        if self.on_connected:
            self.on_connected()
        return True, f"已连接 GTP 引擎 {host}:{port}"

    def start_tcp_server(self, host, port):
        """监听端口，等引擎主动连进来（如 StandardIOToTcp 转发程序）。"""
        with self._lock:
            if self._running:
                return False, "引擎已在运行"
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind((host or "0.0.0.0", int(port)))
            srv.listen(1)
        except Exception as exc:
            try:
                srv.close()
            except Exception:
                pass
            return False, f"监听 {host}:{port} 失败: {exc}"
        self._tcp_host, self._tcp_port = host, int(port)
        self._mode = "tcp-server"
        self._remote_mode = True
        self._ssh_mode = False
        self._server_sock = srv
        self._running = True
        threading.Thread(target=self._accept_loop, args=(srv,), daemon=True).start()
        return True, f"正在监听 {host}:{port}，等待 GTP 引擎连接"

    def _accept_loop(self, srv):
        while self._running and self._server_sock is srv:
            try:
                srv.settimeout(1.0)
                conn, addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with self._lock:
                old = self._sock
                self._sock = conn
            if old is not None:
                try:
                    old.close()
                except OSError:
                    pass
                if self.on_output:
                    self.on_output(">>> [连接] 新引擎接入，已断开旧连接")
            if self.on_output:
                self.on_output(f">>> [连接] GTP 引擎已接入 {addr[0]}:{addr[1]}")
            self._start_writer()
            self._spawn_reader(conn)
            if self.on_connected:
                self.on_connected()

    def _spawn_reader(self, conn):
        threading.Thread(target=self._read_socket_loop, args=(conn,), daemon=True).start()

    def _read_socket_loop(self, conn):
        buffer = b""
        while self._running and self._sock is conn:
            try:
                data = conn.recv(4096)
                if not data:
                    break
                buffer += data
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    text = line.decode("utf-8", errors="ignore").rstrip("\r")
                    if text and self.on_output:
                        self.on_output(text)
            except OSError:
                break
            except Exception:
                break
        self._socket_lost(conn)

    def _socket_lost(self, conn=None):
        if conn is not None and self._sock is not conn:
            return
        with self._lock:
            sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        if not self._running:
            return
        if self.on_output:
            self.on_output(">>> [断开] 与 GTP 引擎的 TCP 连接断开了")
        if self.on_disconnected:
            self.on_disconnected()
        if self._mode == "tcp-client" and self._auto_reconnect:
            self._start_reconnect_loop()

    def _start_reconnect_loop(self):
        if self._reconnect_thread is not None and self._reconnect_thread.is_alive():
            return
        gen = self._reconnect_gen
        self._reconnect_thread = threading.Thread(
            target=self._reconnect_loop, args=(gen,), daemon=True)
        self._reconnect_thread.start()

    def _reconnect_loop(self, gen):
        while self._running and gen == self._reconnect_gen and self._sock is None:
            time.sleep(max(1, int(self._reconnect_interval)))
            if not self._running or gen != self._reconnect_gen or self._sock is not None:
                return
            try:
                sock = socket.create_connection(
                    (self._tcp_host, self._tcp_port), timeout=5)
                sock.settimeout(None)
            except Exception:
                continue
            self._sock = sock
            if self.on_output:
                self.on_output(
                    f">>> [重连] 已重新连接 GTP 引擎 {self._tcp_host}:{self._tcp_port}")
            self._start_writer()
            self._spawn_reader(sock)
            if self.on_connected:
                self.on_connected()
            return

    def set_auto_reconnect(self, enabled, interval=5):
        self._auto_reconnect = bool(enabled)
        self._reconnect_interval = max(1, int(interval))

    def is_listening(self):
        return self._running and self._server_sock is not None

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
            # NAT 保活，防止长时间无流量被路由器断开
            ssh.get_transport().set_keepalive(30)
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
        self._mode = "ssh"
        self._remote_mode = False
        self._reader_thread = threading.Thread(target=self._read_ssh_loop, daemon=True)
        self._reader_thread.start()
        self._start_writer()
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
                            self.on_output(text)
                else:
                    time.sleep(0.01)
            except Exception:
                break

        self._running = False
        if self.on_exit:
            self.on_exit()

    # ---------- 写线程 ----------
    def _start_writer(self):
        if self._writer_thread is not None and self._writer_thread.is_alive():
            return
        # 新会话开始：清掉上一次停止时可能残留的旧命令/退出信号
        self._drain_writes()
        self._writer_gen += 1
        gen = self._writer_gen
        self._writer_thread = threading.Thread(
            target=self._write_loop, args=(gen,), daemon=True)
        self._writer_thread.start()

    def _write_loop(self, gen):
        """写线程：只在属于自己这一代时工作。

        stop() 会把 _writer_gen 加一，旧线程最多 0.2 秒后自行退出；
        这样重启引擎时不会出现「旧写线程吃掉新命令」或「残留退出信号
        让新写线程立刻退出」的问题。
        """
        while gen == self._writer_gen:
            try:
                text = self._write_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if text is None:
                break
            if gen != self._writer_gen:
                break
            try:
                if self._sock is not None:
                    self._sock.sendall(text.encode("utf-8"))
                elif self._ssh_mode and self._ssh_channel:
                    self._ssh_channel.send(text.encode("utf-8"))
                elif self.proc and self.proc.poll() is None and self.proc.stdin:
                    self.proc.stdin.write(text.encode("utf-8"))
                    self.proc.stdin.flush()
            except Exception:
                # 引擎已退出/管道断开：丢掉这条，继续等后续命令或退出信号
                continue

    def _drain_writes(self):
        try:
            while True:
                self._write_queue.get_nowait()
        except queue.Empty:
            return

    def send(self, text):
        """把一行 GTP 命令放进发送队列（立即返回，绝不在调用线程里等管道）。"""
        if not text.endswith("\n"):
            text += "\n"
        if self._sock is not None:
            self._write_queue.put(text)
            return True
        if self._ssh_mode:
            if not self._ssh_channel or self._ssh_channel.closed:
                return False
            self._write_queue.put(text)
            return True
        if not self.proc or self.proc.poll() is not None:
            return False
        self._write_queue.put(text)
        return True

    def stop(self):
        with self._lock:
            was_running = self._running
            self._running = False
            self._reconnect_gen += 1
            # 关掉 TCP 连接与监听
            sock, self._sock = self._sock, None
            if sock is not None:
                try:
                    if self.on_output:
                        self.on_output(">>> [停止] TCP 连接已关闭")
                    sock.sendall(b"quit\n")
                except Exception:
                    pass
                try:
                    sock.close()
                except OSError:
                    pass
            srv, self._server_sock = self._server_sock, None
            if srv is not None:
                try:
                    srv.close()
                except OSError:
                    pass
            if self._ssh_mode:
                if self._ssh_channel:
                    if self.on_output:
                        self.on_output(">>> [停止] quit")
                    try:
                        self._ssh_channel.send("quit\n")
                    except Exception:
                        pass
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
                # 先清掉未发送的积压命令，再发 GTP quit，让引擎自然退出
                try:
                    if self.proc.stdin and self.proc.poll() is None:
                        if self.on_output:
                            self.on_output(">>> [停止] quit")
                        self._drain_writes()
                        self._write_queue.put("quit\n")
                except Exception:
                    pass
                # 给引擎最多 2 秒自然退出
                deadline = time.time() + 2.0
                while time.time() < deadline:
                    if self.proc.poll() is not None:
                        break
                    time.sleep(0.05)
                # 超时未退出则强制终止
                if self.proc.poll() is None:
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
            # 让旧写线程退出（代际 +1 后它最多 0.2 秒自行结束），
            # 不再往队列里塞 None，避免残留信号把重启后的新写线程顶掉。
            self._writer_gen += 1
            if self._writer_thread is not None:
                self._writer_thread.join(1.0)
                self._writer_thread = None
        return True

    def is_running(self):
        if self._mode.startswith("tcp"):
            return self._running and self._sock is not None
        if self._ssh_mode and self._ssh_channel:
            return self._running and not self._ssh_channel.closed
        return self._running and self.proc is not None and self.proc.poll() is None
