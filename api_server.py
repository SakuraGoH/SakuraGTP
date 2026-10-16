import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse


class APIServer:
    def __init__(self, app, host="127.0.0.1", port=8765, on_log=None):
        self.app = app
        self.host = host
        self.port = port
        self.on_log = on_log
        self.httpd = None
        self._thread = None
        self._running = False

        # Token 认证
        self.token_enabled = False
        self.token = ""

    def set_token(self, enabled, token=""):
        self.token_enabled = bool(enabled)
        self.token = token or ""
        self.log(f"API Token 认证: {'开' if self.token_enabled else '关'}")

    def log(self, msg):
        if self.on_log:
            self.on_log(f"[API] {msg}")

    def start(self):
        if self._running:
            return False, "API 已在运行"
        try:
            handler = self._make_handler()
            self.httpd = HTTPServer((self.host, self.port), handler)
            self._running = True
            self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
            self._thread.start()
            self.log(f"HTTP API 已启动: http://{self.host}:{self.port}")
            return True, f"API 启动成功: http://{self.host}:{self.port}"
        except Exception as e:
            self._running = False
            return False, f"API 启动失败: {e}"

    def stop(self):
        if not self._running:
            return
        self._running = False
        if self.httpd:
            try:
                self.httpd.shutdown()
            except Exception:
                pass
            self.httpd = None
        self.log("HTTP API 已停止")

    def is_running(self):
        return self._running

    def _make_handler(self):
        app = self.app
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def _send_json(self, data, status=200):
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)

            def _check_token(self):
                if not server.token_enabled:
                    return True
                auth = self.headers.get("Authorization", "")
                if auth != f"Bearer {server.token}":
                    self._send_json({"error": "unauthorized"}, 401)
                    return False
                return True

            def _read_body(self):
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0:
                        return {}
                    body = self.rfile.read(length).decode("utf-8")
                    return json.loads(body)
                except Exception:
                    return {}

            def do_GET(self):
                if not self._check_token():
                    return
                parsed = urlparse(self.path)
                path = parsed.path

                if path == "/":
                    self._send_json({
                        "name": "SakuraGTP API",
                        "version": "1.3.3",
                        "auth": server.token_enabled,
                        "endpoints": [
                            "GET /status",
                            "GET /board",
                            "GET /candidates",
                            "GET /winrate",
                            "GET /score",
                            "GET /engine",
                            "GET /version",
                            "POST /gtp",
                            "POST /engine/start",
                            "POST /engine/stop",
                            "POST /fox/start",
                            "POST /fox/stop",
                            "POST /rules",
                        ]
                    })
                    return
                if path == "/version":
                    self._send_json({"version": "1.3.3"})
                    return
                if path == "/status":
                    self._send_json(app._api_status())
                    return
                if path == "/board":
                    self._send_json(app._api_board())
                    return
                if path == "/candidates":
                    self._send_json(app._api_candidates())
                    return
                if path == "/winrate":
                    self._send_json(app._api_winrate())
                    return
                if path == "/score":
                    self._send_json(app._api_score())
                    return
                if path == "/engine":
                    self._send_json(app._api_engine_info())
                    return
                self._send_json({"error": "not found"}, 404)

            def do_POST(self):
                if not self._check_token():
                    return
                parsed = urlparse(self.path)
                path = parsed.path
                body = self._read_body()

                if path == "/gtp":
                    cmd = body.get("command", "").strip()
                    if not cmd:
                        self._send_json({"error": "command required"}, 400)
                        return
                    ok = app._api_send_gtp(cmd)
                    self._send_json({"ok": ok})
                    return
                if path == "/engine/start":
                    ok, msg = app._api_start_engine()
                    self._send_json({"ok": ok, "message": msg})
                    return
                if path == "/engine/stop":
                    ok, msg = app._api_stop_engine()
                    self._send_json({"ok": ok, "message": msg})
                    return
                if path == "/fox/start":
                    ok, msg = app._api_start_fox()
                    self._send_json({"ok": ok, "message": msg})
                    return
                if path == "/fox/stop":
                    ok, msg = app._api_stop_fox()
                    self._send_json({"ok": ok, "message": msg})
                    return
                if path == "/rules":
                    rule = body.get("rule", "").strip()
                    if not rule:
                        self._send_json({"error": "rule required"}, 400)
                        return
                    app._api_set_rules(rule)
                    self._send_json({"ok": True})
                    return
                self._send_json({"error": "not found"}, 404)

            def do_OPTIONS(self):
                self.send_response(200)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
                self.end_headers()

        return Handler