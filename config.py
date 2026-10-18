import json
import os
import sys

def get_config_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(get_config_dir(), "sakura_config.json")

DEFAULT_CONFIG = {
    "engine_path": "",
    "weight_path": "",
    "config_path": "",
    "engine_args": "",
    "comm_cmd": "",
    "engine_mode": "local",
    "background_image": "",
    "fox_listen_port": 6000,
    "ai_listen_port": 8000,
    "comm_mode": "stdio",
    "ai_ip": "127.0.0.1",
    "ai_port": 8000,
    "use_common_byo_yomi": False,
    "data_transfer_time": 1,
    "specify_ai_byo_yomi": False,
    "ai_byo_yomi_time": 5,
    "use_protocol_version_heartbeat": False,
    "heartbeat_interval": 60,
    "engine_history": [],
    "weight_history": [],
    "config_history": [],
    "remote_cmd": "",
    "window_geometry": "",
    "log_split": True,
    "max_time": 5,
    "max_visits": 0,
    "max_playouts": 0,
    "gtp_snippets": [],
    "api_port": 8765,
    "api_enabled": False,
    "bg_color": "#F0F0F0",
    "dark_winrate_bg": False,
    "dark_board_bg": False,
    "ssh_host": "",
    "ssh_port": "22",
    "ssh_user": "",
    "ssh_cmd": "",
    "version": "1.4.0",
    # 心跳包
    "heartbeat_enabled": False,
    "heartbeat_interval": 30,       # 秒
    "heartbeat_timeout": 10,        # 秒，超过判定假死
    # 自动跑谱
    "auto_contribute": False,
    "contribute_command": "",
    "contribute_idle_seconds": 300,     # 空闲多少秒后启动跑谱
    "contribute_stop_on_game": True,    # 有对局立刻停止

    # 断线重连
    "auto_reconnect": True,
    "reconnect_interval": 5,        # 秒

    # API Token
    "api_token_enabled": False,
    "api_token": "",
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            cfg = DEFAULT_CONFIG.copy()
            cfg.update(data)
            snippets = cfg.get("gtp_snippets", [])
            if isinstance(snippets, dict):
                snippets = list(snippets.values())
                cfg["gtp_snippets"] = snippets
            elif not isinstance(snippets, list):
                cfg["gtp_snippets"] = []
            if "version" not in cfg:
                cfg["version"] = "1.3.0"
            if "bg_color" not in cfg:
                cfg["bg_color"] = "#F0F0F0"
            if "dark_winrate_bg" not in cfg:
                cfg["dark_winrate_bg"] = False
            if "dark_board_bg" not in cfg:
                cfg["dark_board_bg"] = False
            if "comm_cmd" not in cfg:
                cfg["comm_cmd"] = ""
            if "engine_mode" not in cfg:
                cfg["engine_mode"] = "local"
            if "heartbeat_enabled" not in cfg:
                cfg["heartbeat_enabled"] = False
            if "heartbeat_interval" not in cfg:
                cfg["heartbeat_interval"] = 30
            if "heartbeat_timeout" not in cfg:
                cfg["heartbeat_timeout"] = 10
            if "auto_reconnect" not in cfg:
                cfg["auto_reconnect"] = True
            if "reconnect_interval" not in cfg:
                cfg["reconnect_interval"] = 5
            if "api_token_enabled" not in cfg:
                cfg["api_token_enabled"] = False
            if "api_token" not in cfg:
                cfg["api_token"] = ""
            if "auto_contribute" not in cfg:
                cfg["auto_contribute"] = False
            if "contribute_command" not in cfg:
                cfg["contribute_command"] = ""
            if "contribute_idle_seconds" not in cfg:
                cfg["contribute_idle_seconds"] = 300
            if "contribute_stop_on_game" not in cfg:
                cfg["contribute_stop_on_game"] = True
            return cfg
        except Exception:
            return DEFAULT_CONFIG.copy()
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def push_history(cfg, key, value, max_len=20):
    if not value:
        return
    hist = cfg.get(key, [])
    if not isinstance(hist, list):
        hist = []
    if value in hist:
        hist.remove(value)
    hist.insert(0, value)
    cfg[key] = hist[:max_len]
