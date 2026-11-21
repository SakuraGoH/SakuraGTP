"""Persistent settings (FoxGTP keeps these in the registry; we use JSON)."""

import copy
import json
import os
import sys

APP_NAME = "FoxGTP-Py"


def app_dir():
    """Directory that holds the executable / entry script."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _config_candidates():
    here = app_dir()
    portable = os.path.join(here, "config.json")
    appdata = os.path.join(os.environ.get("APPDATA", here), APP_NAME, "config.json")
    return portable, appdata


CONFIG_PATH = _config_candidates()[0]


DEFAULT_CONFIG = {
    # ---- AI engine -----------------------------------------------------
    "channel": "stdio",            # stdio / tcp-client / tcp-server
    "engine_path": "",
    "engine_args": "",
    "engine_command": "",          # optional full command line (overrides path+args)
    "working_dir": "",
    "engine_host": "127.0.0.1",
    "engine_port": 8000,
    "engine_ready_timeout": 120,   # seconds to wait for the first protocol_version

    # ---- Wild Fox client ----------------------------------------------
    "fox_port": 6000,
    "fox_host": "0.0.0.0",

    # ---- heartbeat / recovery -----------------------------------------
    "heartbeat_enabled": False,
    "heartbeat_interval": 30,
    "heartbeat_timeout": 10,
    "auto_recover": True,
    "recover_interval": 5,

    # ---- time translation (FoxGTP 4.4.1 / 4.4.2) ----------------------
    "use_go_byoyomi": False,
    "use_data_transfer_time": False,
    "data_transfer_time": 1,
    "use_ai_cal_time": False,
    "ai_cal_time": 5,

    # ---- search limits (KataGo kata-set-param; others use time) --------
    "max_time": 0.0,
    "max_visits": 0,
    "max_playouts": 0,

    # ---- analysis / candidates (optional, never required) --------------
    "use_analyze": True,
    "analyze_interval_ms": 50,
    "analyze_max_moves": 12,
    "genmove_timeout": 0.0,        # 0 = auto (byo*2+20 / max_time+30 / >= 60)

    # ---- rules / handicap ---------------------------------------------
    "rule": "",
    "handicap_mode": "auto",       # auto / free / fixed / play

    # ---- UI ------------------------------------------------------------
    "language": "zh",
    "show_candidates": True,
    "show_move_numbers": False,
    "show_coordinates": True,
    "timestamp_in_log": True,
    "save_log": True,
    "log_dir": "logs",
    "window_geometry": "",
    "ai_board_geometry": "",
    "fox_board_geometry": "",
    "log_geometry": "",

    # ---- histories -----------------------------------------------------
    "engine_history": [],
}

MAX_HISTORY = 20


def load_config():
    """Load and merge with defaults; never raises."""
    config = copy.deepcopy(DEFAULT_CONFIG)
    portable, appdata = _config_candidates()
    for path in (portable, appdata):
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                config.update(data)
        except Exception:
            pass
        break
    return config


def save_config(config):
    path = CONFIG_PATH
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(config, handle, ensure_ascii=False, indent=2, sort_keys=True)
        return True
    except Exception:
        # fall back to %APPDATA%
        _, fallback = _config_candidates()
        try:
            os.makedirs(os.path.dirname(fallback), exist_ok=True)
            with open(fallback, "w", encoding="utf-8") as handle:
                json.dump(config, handle, ensure_ascii=False, indent=2, sort_keys=True)
            return True
        except Exception:
            return False


def push_history(config, key, value):
    if not value:
        return
    history = config.get(key) or []
    if not isinstance(history, list):
        history = []
    if value in history:
        history.remove(value)
    history.insert(0, value)
    config[key] = history[:MAX_HISTORY]


def build_engine_command(config):
    """Compose the STDIO command line from path + args (unless overridden)."""
    override = (config.get("engine_command") or "").strip()
    if override:
        return override
    path = (config.get("engine_path") or "").strip()
    if not path:
        return ""
    args = (config.get("engine_args") or "").strip()
    if not args:
        return '"%s"' % path
    return '"%s" %s' % (path, args)


def resolve_working_dir(config):
    working = (config.get("working_dir") or "").strip()
    if working:
        return working
    path = (config.get("engine_path") or "").strip()
    if path and os.path.isfile(path):
        return os.path.dirname(os.path.abspath(path))
    return ""
