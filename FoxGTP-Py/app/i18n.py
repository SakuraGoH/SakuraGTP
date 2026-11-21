"""Tiny CN/EN translation table (FoxGTP has the same language switch)."""

STRINGS = {
    # window / menus
    "app_title": ("FoxGTP-Py 1.0 - 野狐围棋 AI 连线器", "FoxGTP-Py 1.0 - Fox Go AI Connector"),
    "menu_work": ("工作", "Work"),
    "menu_comm": ("通信", "Communication"),
    "menu_board": ("棋盘", "Board"),
    "menu_tools": ("工具", "Tools"),
    "menu_help": ("帮助", "Help"),
    "action_start_fox": ("开始监听野狐客户端", "Start listening for Fox client"),
    "action_stop_fox": ("停止监听野狐客户端", "Stop listening for Fox client"),
    "action_connect": ("连接 AI 引擎", "Connect AI engine"),
    "action_disconnect": ("断开 AI 引擎", "Disconnect AI engine"),
    "action_settings": ("设置...", "Settings..."),
    "action_shell": ("GTP Shell", "GTP Shell"),
    "action_log": ("通信数据", "Communication data"),
    "action_fox_board": ("野狐棋盘", "Fox client board"),
    "action_ai_board": ("AI 引擎棋盘", "AI engine board"),
    "action_query_status": ("向野狐查询状态", "Query Fox client status"),
    "action_clear_log": ("清空通信数据", "Clear communication data"),
    "action_open_log": ("打开日志目录", "Open log directory"),
    "action_help": ("使用说明", "How to use"),
    "action_about": ("关于 FoxGTP-Py", "About FoxGTP-Py"),
    "action_exit": ("退出", "Exit"),
    "action_lang": ("English", "简体中文"),

    # groups
    "group_fox": ("野狐客户端", "Fox Go client"),
    "group_engine": ("AI 引擎", "AI engine"),
    "group_options": ("对局选项", "Game options"),
    "group_log": ("通信数据", "Communication data"),

    # labels
    "label_port": ("端口", "Port"),
    "label_host": ("地址", "Host"),
    "label_channel": ("通信方式", "Channel"),
    "label_path": ("引擎程序", "Engine"),
    "label_args": ("命令行参数", "Arguments"),
    "label_command": ("命令行", "Command line"),
    "label_workdir": ("工作目录", "Working dir"),
    "label_rule": ("规则", "Rules"),
    "label_state": ("状态", "State"),
    "label_move": ("手数", "Move"),
    "label_winrate": ("胜率", "Winrate"),
    "label_score": ("目差", "Score lead"),
    "label_language": ("语言", "Language"),
    "label_handicap_mode": ("让子方式", "Handicap mode"),

    # buttons
    "btn_start": ("开始监听", "Start"),
    "btn_stop": ("停止", "Stop"),
    "btn_connect": ("连接", "Connect"),
    "btn_disconnect": ("断开", "Disconnect"),
    "btn_browse": ("浏览...", "Browse..."),
    "btn_ok": ("确定", "OK"),
    "btn_cancel": ("取消", "Cancel"),
    "btn_apply": ("应用", "Apply"),
    "btn_send": ("发送", "Send"),
    "btn_clear": ("清空", "Clear"),
    "btn_new_game": ("新对局", "New game"),

    # channels
    "channel_stdio": ("标准输入输出 (STDIO)", "Standard I/O (STDIO)"),
    "channel_tcp_client": ("TCP/IP: FoxGTP → AI 引擎", "TCP/IP: FoxGTP -> AI engine"),
    "channel_tcp_server": ("TCP/IP: AI 引擎 → FoxGTP", "TCP/IP: AI engine -> FoxGTP"),

    # options
    "opt_go_byoyomi": ("使用围棋常用读秒（N 秒 × M 次，非加拿大读秒）",
                       "Go-style byo-yomi (N sec x M periods, not Canadian)"),
    "opt_data_transfer": ("指定数据传输耗时（秒）", "Data transfer time (sec)"),
    "opt_ai_cal_time": ("指定 AI 引擎读秒时间（秒）", "Specify AI engine byo-yomi (sec)"),
    "opt_heartbeat": ("使用 protocol_version 作为心跳包",
                      "Use protocol_version as heartbeat"),
    "opt_auto_recover": ("AI 引擎断开后自动重连", "Auto reconnect AI engine"),
    "opt_analysis": ("使用分析命令显示候选点与胜率（支持时）",
                     "Show candidates/winrate when the engine supports analyze"),
    "opt_test_mode": ("测试模式（可直接在 AI 棋盘上落子）",
                      "Test mode (play directly on the AI board)"),
    "opt_timestamp": ("时间戳", "Timestamp"),
    "opt_save_log": ("保存通信数据到日志文件", "Save communication data to log file"),
    "opt_coordinates": ("显示坐标", "Show coordinates"),
    "opt_move_numbers": ("显示手数", "Show move numbers"),

    # states
    "state_engine_off": ("未连接", "Disconnected"),
    "state_engine_connected": ("已连接", "Connected"),
    "state_engine_ready": ("就绪", "Ready"),
    "state_fox_waiting": ("等待野狐连接", "Waiting for Fox client"),
    "state_fox_connected": ("野狐已连接", "Fox client connected"),
    "state_fox_off": ("未监听", "Not listening"),

    # dialogs
    "settings_title": ("设置", "Settings"),
    "shell_title": ("GTP Shell - 直接与 AI 引擎交互", "GTP Shell - talk to the engine"),
    "about_title": ("关于 FoxGTP-Py", "About FoxGTP-Py"),
    "help_title": ("使用说明", "How to use"),
    "fox_board_title": ("野狐棋盘", "Fox client board"),
    "ai_board_title": ("AI 引擎棋盘", "AI engine board"),
    "tab_engine": ("AI 引擎", "AI engine"),
    "tab_fox": ("野狐客户端", "Fox client"),
    "tab_time": ("读秒", "Byo-yomi"),
    "tab_search": ("搜索/分析", "Search / analysis"),
    "tab_ui": ("界面", "Interface"),

    # misc
    "candidates": ("候选点", "Candidates"),
    "no_candidates": ("（暂无候选点，引擎未提供分析数据）",
                      "(no candidates - the engine provides no analysis)"),
    "ready_hint": ("选择引擎、点击「连接」，再「开始监听」，最后在野狐里连接过来。",
                   "Connect the engine, start listening, then point the Fox client at it."),
}


class Language:
    def __init__(self, code="zh"):
        self.code = code if code in ("zh", "en") else "zh"

    def __call__(self, key):
        entry = STRINGS.get(key)
        if not entry:
            return key
        return entry[0] if self.code == "zh" else entry[1]

    def toggle(self):
        self.code = "en" if self.code == "zh" else "zh"
        return self.code

    def set(self, code):
        self.code = code if code in ("zh", "en") else "zh"
