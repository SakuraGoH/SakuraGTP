import json
import os
import sys

from theme import sci_fi_bg


def get_config_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
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
    # 引擎连接方式（对齐 FoxGTP 的通信菜单）：0=本地进程 1=TCP 客户端 2=TCP 服务端
    "engine_link_mode": 0,
    "engine_tcp_host": "127.0.0.1",
    "engine_tcp_port": 8888,
    "engine_tcp_auto_reconnect": True,
    "use_common_byo_yomi": False,
    "data_transfer_time": 1,
    "specify_ai_byo_yomi": False,
    "ai_byo_yomi_time": 5,
    "engine_history": [],
    "weight_history": [],
    "config_history": [],
    "remote_cmd": "",
    "window_geometry": "",
    "log_split": True,
    # 通信协议 / GTP 输出每隔多少分钟清一次旧内容（0 = 不清）
    "log_auto_clear_minutes": 5,
    # GTP 输出页是否显示引擎的分析/调试行（info move、KataGo 日志等）。
    # 默认关闭：这些行每 50ms 刷一次、单行可达数 KB，会把日志淹没。
    "log_engine_debug": False,
    "max_time": 5,
    "max_visits": 0,
    "max_playouts": 0,
    "gtp_snippets": [],
    "api_port": 8765,
    "api_enabled": False,
    "bg_color": sci_fi_bg(),          # 默认深空蓝科幻背景
    "bg_mode": "starfield",           # 个性化背景：starfield 星空 / daynight 昼夜更替
    "ssh_host": "",
    "ssh_port": "22",
    "ssh_user": "",
    "ssh_cmd": "",
    "version": "1.6.6",
    # 心跳包
    "heartbeat_enabled": False,
    "heartbeat_interval": 30,         # 秒
    "heartbeat_timeout": 10,          # 秒，超过判定假死
    # 自动跑谱
    "auto_contribute": False,
    "contribute_command": "",
    "contribute_idle_seconds": 300,   # 空闲多少秒后启动跑谱
    "contribute_stop_on_game": True,  # 有对局立刻停止
    # 断线重连
    "auto_reconnect": True,
    "reconnect_interval": 5,          # 秒
    # 每局结束后重启一次引擎（清理引擎长局积累的状态/内存）
    "restart_engine_after_game": False,
    # API Token
    "api_token_enabled": False,
    "api_token": "",
}


def load_config():
    """读取配置，与默认值合并；损坏或缺失时返回默认配置副本。"""
    cfg = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cfg.update(data)
        except Exception:
            pass

    # 兼容历史格式：gtp_snippets 曾是 dict
    snippets = cfg.get("gtp_snippets", [])
    if isinstance(snippets, dict):
        snippets = list(snippets.values())
    elif not isinstance(snippets, list):
        snippets = []
    cfg["gtp_snippets"] = snippets

    for key in ("engine_history", "weight_history", "config_history"):
        if not isinstance(cfg.get(key), list):
            cfg[key] = []
    return cfg


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
