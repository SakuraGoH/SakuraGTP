import socket
import re
import os
import threading
import secrets
import time

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QComboBox, QFileDialog, QMessageBox,
    QTabWidget, QTextEdit, QCheckBox, QSpinBox, QGroupBox, QFormLayout,
    QDialog, QListWidget, QPlainTextEdit, QSlider, QScrollArea,
    QStackedWidget
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPalette

from config import load_config, save_config, push_history
from engine_manager import EngineManager
from fox_client import FoxClientServer
from gtp_bridge import GTPBridge
from board_view import BoardView
from winrate_view import WinrateView
from api_server import APIServer
from runner import ContributeRunner


class SakuraGTPApp(QMainWindow):
    comm_signal = pyqtSignal(str)
    gtp_signal = pyqtSignal(str)
    candidate_signal = pyqtSignal(list)
    board_signal = pyqtSignal()
    engine_exit_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("SakuraGTP 1.4.1 - 野狐围棋 AI 连线器")
        self.resize(1800, 1000)

        self.cfg = load_config()

        self.engine = EngineManager(
            on_output=self._on_engine_output,
            on_exit=self._on_engine_exit_signal,
        )
        self.fox = FoxClientServer(
            on_command=self._on_fox_command,
            on_log=self._log_comm,
            on_reconnect=self._on_fox_reconnect,
        )
        self.bridge = GTPBridge(
            engine_manager=self.engine,
            send_to_fox=self.fox.send,
            on_log=self._log_comm,
            on_candidate=self._on_candidate,
            on_engine_raw=self._on_engine_raw,
        )

        self.winrate_window = None
        self._detached_view = None
        self.api_window = None

        self.api_server = APIServer(self, on_log=self._log_comm)
        self.runner = ContributeRunner(on_log=self._log_comm)
        self._last_game_time = time.time()
        self._idle_thread = threading.Thread(target=self._idle_loop, daemon=True)
        self._idle_thread.start()

        self._build_ui()
        self._connect_signals()
        self._on_live_winrate_change(False)

        bg_color = self.cfg.get("bg_color", "#F0F0F0")
        self._apply_bg_color(bg_color)

        if self.cfg.get("dark_winrate_bg", False):
            self.winrate_view.set_dark_mode(True)
        if self.cfg.get("dark_board_bg", False):
            self.board_view.set_dark_mode(True)

        self.ssh_host_edit.setText(self.cfg.get("ssh_host", ""))
        self.ssh_port_edit.setText(self.cfg.get("ssh_port", "22"))
        self.ssh_user_edit.setText(self.cfg.get("ssh_user", ""))
        self.ssh_key_edit.setText(self.cfg.get("ssh_key", ""))
        self.ssh_cmd_edit.setText(self.cfg.get("ssh_cmd", ""))

        mode = self.cfg.get("engine_mode", "local")
        self._switch_mode(mode)

        # 心跳
        hb_enabled = self.cfg.get("heartbeat_enabled", False)
        hb_interval = self.cfg.get("heartbeat_interval", 30)
        hb_timeout = self.cfg.get("heartbeat_timeout", 10)
        self.engine.set_heartbeat(hb_enabled, hb_interval, hb_timeout)

        # 断线重连
        rc_enabled = self.cfg.get("auto_reconnect", True)
        rc_interval = self.cfg.get("reconnect_interval", 5)
        self.fox.set_auto_reconnect(rc_enabled, rc_interval)

        # API Token
        token_enabled = self.cfg.get("api_token_enabled", False)
        token = self.cfg.get("api_token", "")
        self.api_server.set_token(token_enabled, token)

        if self.cfg.get("api_enabled", False):
            try:
                port = int(self.cfg.get("api_port", 8765))
            except ValueError:
                port = 8765
            self.api_server.host = "127.0.0.1"
            self.api_server.port = port
            ok, msg = self.api_server.start()
            self._log_comm(msg)

    def _build_ui(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("文件")
        file_menu.addAction("保存配置", self._save_cfg)
        file_menu.addAction("退出", self.close)

        view_menu = menubar.addMenu("视图")
        view_menu.addAction("界面背景色", self._open_bg_color_dialog)
        view_menu.addAction("暗色胜率曲线背景", self._toggle_dark_winrate)
        view_menu.addAction("暗色棋盘", self._toggle_dark_board)

        tools_menu = menubar.addMenu("工具")
        tools_menu.addAction("HTTP API", self._open_api_window)
        tools_menu.addAction("自动跑谱设置", self._open_contribute_dialog)
        tools_menu.addAction("手动停止跑谱", self._manual_stop_contribute)
        tools_menu.addSeparator()
        tools_menu.addAction("心跳设置", self._open_heartbeat_dialog)
        tools_menu.addAction("断线重连设置", self._open_reconnect_dialog)
        tools_menu.addAction("API Token 设置", self._open_token_dialog)

        help_menu = menubar.addMenu("帮助")
        help_menu.addAction("依赖环境", self._show_env_help)
        help_menu.addAction("使用说明", self._show_usage_help)
        help_menu.addAction("关于", self._show_about)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setMinimumWidth(840)
        left_scroll.setMaximumWidth(1100)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        left_scroll.setFrameShape(QScrollArea.NoFrame)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        self._build_left(left_layout)
        left_scroll.setWidget(left)

        self.left_scroll = left_scroll
        self._build_right(main_layout, left_scroll)

    def _build_left(self, layout):
        mode_group = QGroupBox("引擎模式")
        mode_layout = QHBoxLayout()
        self.btn_mode_local = QPushButton("本地引擎")
        self.btn_mode_local.clicked.connect(lambda: self._switch_mode("local"))
        self.btn_mode_ssh = QPushButton("SSH 连接")
        self.btn_mode_ssh.clicked.connect(lambda: self._switch_mode("ssh"))
        mode_layout.addWidget(self.btn_mode_local)
        mode_layout.addWidget(self.btn_mode_ssh)
        mode_group.setLayout(mode_layout)
        layout.addWidget(mode_group)

        self.mode_stack = QStackedWidget()

        # ---------- 本地模式 ----------
        local_page = QWidget()
        local_layout = QVBoxLayout(local_page)
        local_layout.setContentsMargins(0, 0, 0, 0)

        engine_group = QGroupBox("本地引擎设置")
        engine_form = QFormLayout()
        engine_form.setVerticalSpacing(10)
        engine_form.setHorizontalSpacing(8)
        engine_form.setContentsMargins(8, 8, 8, 8)

        self.engine_combo = QComboBox()
        self.engine_combo.setEditable(True)
        self.engine_combo.addItems(self.cfg.get("engine_history", []))
        self.engine_combo.setCurrentText(self.cfg.get("engine_path", ""))
        self.engine_combo.setMinimumHeight(34)
        self.btn_browse_engine = QPushButton("浏览")
        self.btn_browse_engine.clicked.connect(self._browse_engine)
        row = QHBoxLayout()
        row.addWidget(self.engine_combo)
        row.addWidget(self.btn_browse_engine)
        engine_form.addRow("引擎:", row)

        self.weight_combo = QComboBox()
        self.weight_combo.setEditable(True)
        self.weight_combo.addItems(self.cfg.get("weight_history", []))
        self.weight_combo.setCurrentText(self.cfg.get("weight_path", ""))
        self.weight_combo.setMinimumHeight(34)
        self.btn_browse_weight = QPushButton("浏览")
        self.btn_browse_weight.clicked.connect(self._browse_weight)
        row = QHBoxLayout()
        row.addWidget(self.weight_combo)
        row.addWidget(self.btn_browse_weight)
        engine_form.addRow("权重:", row)

        self.config_combo = QComboBox()
        self.config_combo.setEditable(True)
        self.config_combo.addItems(self.cfg.get("config_history", []))
        self.config_combo.setCurrentText(self.cfg.get("config_path", ""))
        self.config_combo.setMinimumHeight(34)
        self.btn_browse_config = QPushButton("浏览")
        self.btn_browse_config.clicked.connect(self._browse_config)
        row = QHBoxLayout()
        row.addWidget(self.config_combo)
        row.addWidget(self.btn_browse_config)
        engine_form.addRow("配置:", row)

        comm_row = QHBoxLayout()
        self.comm_cmd_edit = QLineEdit(self.cfg.get("comm_cmd", ""))
        self.comm_cmd_edit.setPlaceholderText(
            '通用命令行（本地或 plink/ikatago），例如: plink -ssh ...'
        )
        comm_row.addWidget(self.comm_cmd_edit, stretch=1)

        btn_auto_cmd = QPushButton("自动生成")
        btn_auto_cmd.clicked.connect(self._auto_gen_cmd)
        comm_row.addWidget(btn_auto_cmd)
        engine_form.addRow("通用命令行:", comm_row)

        engine_group.setLayout(engine_form)
        local_layout.addWidget(engine_group)

        local_btn_layout = QHBoxLayout()
        self.btn_start_engine = QPushButton("启动引擎")
        self.btn_start_engine.clicked.connect(self._start_engine)
        self.btn_stop_engine = QPushButton("停止引擎")
        self.btn_stop_engine.clicked.connect(self._stop_engine)
        self.btn_stop_engine.setEnabled(False)
        local_btn_layout.addWidget(self.btn_start_engine)
        local_btn_layout.addWidget(self.btn_stop_engine)
        local_layout.addLayout(local_btn_layout)

        local_fox_group = QGroupBox("野狐客户端监听")
        local_fox_layout = QHBoxLayout()
        local_fox_layout.addWidget(QLabel("端口:"))
        self.fox_port_edit = QLineEdit(str(self.cfg.get("fox_listen_port", 6000)))
        self.fox_port_edit.setFixedWidth(80)
        local_fox_layout.addWidget(self.fox_port_edit)
        self.btn_start_fox_local = QPushButton("开始监听")
        self.btn_start_fox_local.clicked.connect(self._start_fox)
        self.btn_stop_fox_local = QPushButton("停止监听")
        self.btn_stop_fox_local.clicked.connect(self._stop_fox)
        self.btn_stop_fox_local.setEnabled(False)
        local_fox_layout.addWidget(self.btn_start_fox_local)
        local_fox_layout.addWidget(self.btn_stop_fox_local)
        local_fox_group.setLayout(local_fox_layout)
        local_layout.addWidget(local_fox_group)

        local_layout.addStretch()
        self.mode_stack.addWidget(local_page)

        # ---------- SSH 模式 ----------
        ssh_page = QWidget()
        ssh_layout = QVBoxLayout(ssh_page)
        ssh_layout.setContentsMargins(0, 0, 0, 0)

        ssh_group = QGroupBox("SSH 连接设置")
        ssh_form = QFormLayout()
        ssh_form.setVerticalSpacing(10)
        ssh_form.setHorizontalSpacing(8)
        ssh_form.setContentsMargins(8, 8, 8, 8)

        self.ssh_host_edit = QLineEdit("")
        self.ssh_host_edit.setPlaceholderText("远程 IP 或域名")
        ssh_form.addRow("主机:", self.ssh_host_edit)

        self.ssh_port_edit = QLineEdit("22")
        self.ssh_port_edit.setFixedWidth(80)
        ssh_form.addRow("端口:", self.ssh_port_edit)

        self.ssh_user_edit = QLineEdit("")
        self.ssh_user_edit.setPlaceholderText("用户名")
        ssh_form.addRow("用户名:", self.ssh_user_edit)

        self.ssh_pass_edit = QLineEdit("")
        self.ssh_pass_edit.setEchoMode(QLineEdit.Password)
        self.ssh_pass_edit.setPlaceholderText("密码（可选）")
        ssh_form.addRow("密码:", self.ssh_pass_edit)

        key_row = QHBoxLayout()
        self.ssh_key_edit = QLineEdit("")
        self.ssh_key_edit.setPlaceholderText("私钥路径（可选）")
        key_row.addWidget(self.ssh_key_edit, stretch=1)
        btn_browse_key = QPushButton("浏览")
        btn_browse_key.clicked.connect(self._browse_ssh_key)
        key_row.addWidget(btn_browse_key)
        ssh_form.addRow("私钥:", key_row)

        self.ssh_cmd_edit = QLineEdit("")
        self.ssh_cmd_edit.setPlaceholderText(
            '例: cd /root && ./katago gtp -model model.bin.gz -config gtp.cfg'
        )
        ssh_form.addRow("命令:", self.ssh_cmd_edit)

        ssh_group.setLayout(ssh_form)
        ssh_layout.addWidget(ssh_group)

        ssh_btn_layout = QHBoxLayout()
        self.btn_start_ssh = QPushButton("SSH 启动")
        self.btn_start_ssh.clicked.connect(self._start_ssh)
        self.btn_stop_ssh = QPushButton("SSH 停止")
        self.btn_stop_ssh.clicked.connect(self._stop_engine)
        self.btn_stop_ssh.setEnabled(False)
        ssh_btn_layout.addWidget(self.btn_start_ssh)
        ssh_btn_layout.addWidget(self.btn_stop_ssh)
        ssh_layout.addLayout(ssh_btn_layout)

        ssh_fox_group = QGroupBox("野狐客户端监听")
        ssh_fox_layout = QHBoxLayout()
        ssh_fox_layout.addWidget(QLabel("端口:"))
        self.ssh_fox_port_edit = QLineEdit(str(self.cfg.get("fox_listen_port", 6000)))
        self.ssh_fox_port_edit.setFixedWidth(80)
        ssh_fox_layout.addWidget(self.ssh_fox_port_edit)
        self.btn_start_fox_ssh = QPushButton("开始监听")
        self.btn_start_fox_ssh.clicked.connect(self._start_fox_ssh)
        self.btn_stop_fox_ssh = QPushButton("停止监听")
        self.btn_stop_fox_ssh.clicked.connect(self._stop_fox)
        self.btn_stop_fox_ssh.setEnabled(False)
        ssh_fox_layout.addWidget(self.btn_start_fox_ssh)
        ssh_fox_layout.addWidget(self.btn_stop_fox_ssh)
        ssh_fox_group.setLayout(ssh_fox_layout)
        ssh_layout.addWidget(ssh_fox_group)

        ssh_layout.addStretch()
        self.mode_stack.addWidget(ssh_page)

        layout.addWidget(self.mode_stack)

        # 实时胜率
        live_group = QGroupBox("实时胜率")
        live_layout = QVBoxLayout()

        self.live_winrate_check = QCheckBox("启用实时胜率（分析模式）")
        self.live_winrate_check.setChecked(False)
        self.live_winrate_check.stateChanged.connect(self._on_live_winrate_change)
        live_layout.addWidget(self.live_winrate_check)

        self.winrate_param_widget = QWidget()
        param_layout = QFormLayout(self.winrate_param_widget)
        param_layout.setVerticalSpacing(10)
        param_layout.setContentsMargins(0, 0, 0, 0)

        self.max_time_edit = QLineEdit(str(self.cfg.get("max_time", 5)))
        param_layout.addRow("maxTime:", self.max_time_edit)

        self.max_visits_edit = QLineEdit(str(self.cfg.get("max_visits", 0)))
        param_layout.addRow("maxVisits:", self.max_visits_edit)

        self.max_playouts_edit = QLineEdit(str(self.cfg.get("max_playouts", 0)))
        param_layout.addRow("maxPlayouts:", self.max_playouts_edit)

        self.btn_refresh_state = QPushButton("刷新落子参数")
        self.btn_refresh_state.clicked.connect(self._refresh_state)
        param_layout.addRow("", self.btn_refresh_state)

        self.winrate_param_widget.setVisible(False)
        live_layout.addWidget(self.winrate_param_widget)

        live_group.setLayout(live_layout)
        layout.addWidget(live_group)

        # 规则快速切换
        rules_group = QGroupBox("规则快速切换")
        rules_layout = QHBoxLayout()
        self.btn_chinese_rules = QPushButton("中国规则")
        self.btn_chinese_rules.clicked.connect(lambda: self._send_rule("chinese"))
        self.btn_japanese_rules = QPushButton("日本规则")
        self.btn_japanese_rules.clicked.connect(lambda: self._send_rule("japanese"))
        rules_layout.addWidget(self.btn_chinese_rules)
        rules_layout.addWidget(self.btn_japanese_rules)
        rules_group.setLayout(rules_layout)
        layout.addWidget(rules_group)

        # GTP Shell
        shell_group = QGroupBox("GTP Shell")
        shell_layout = QVBoxLayout()

        snippet_row = QHBoxLayout()
        snippet_row.addWidget(QLabel("常用指令:"))
        self.snippet_combo = QComboBox()
        self.snippet_combo.addItem("（无）")
        for s in self.cfg.get("gtp_snippets", []):
            self.snippet_combo.addItem(s)
        self.snippet_combo.currentTextChanged.connect(self._on_snippet_selected)
        snippet_row.addWidget(self.snippet_combo, stretch=1)
        btn_manage_snippets = QPushButton("管理")
        btn_manage_snippets.clicked.connect(self._manage_snippets)
        snippet_row.addWidget(btn_manage_snippets)
        shell_layout.addLayout(snippet_row)

        self.shell_edit = QLineEdit()
        self.shell_edit.returnPressed.connect(self._send_shell)
        shell_layout.addWidget(self.shell_edit)

        btn_send_shell = QPushButton("发送 GTP 命令")
        btn_send_shell.clicked.connect(self._send_shell)
        shell_layout.addWidget(btn_send_shell)

        shell_group.setLayout(shell_layout)
        layout.addWidget(shell_group)

        # 跑谱状态
        self.contribute_group = QGroupBox("跑谱状态")
        contrib_layout = QHBoxLayout()
        self.contribute_label = QLabel("未运行")
        contrib_layout.addWidget(self.contribute_label)
        self.btn_stop_contribute = QPushButton("停止跑谱")
        self.btn_stop_contribute.setEnabled(False)
        self.btn_stop_contribute.clicked.connect(self._manual_stop_contribute)
        contrib_layout.addWidget(self.btn_stop_contribute)
        contrib_layout.addStretch()
        self.contribute_group.setLayout(contrib_layout)
        layout.addWidget(self.contribute_group)

        layout.addStretch()

        layout.addStretch()

    def _build_right(self, main_layout, left_scroll):
        self.tabs = QTabWidget()

        comm_tab = QWidget()
        comm_layout = QVBoxLayout(comm_tab)
        comm_layout.setContentsMargins(2, 2, 2, 2)
        comm_layout.setSpacing(2)

        comm_ctrl = QHBoxLayout()
        comm_ctrl.addStretch()
        btn_clear_comm = QPushButton("清空")
        btn_clear_comm.clicked.connect(self._clear_comm)
        comm_ctrl.addWidget(btn_clear_comm)
        comm_layout.addLayout(comm_ctrl)

        self.comm_text = QTextEdit()
        self.comm_text.setReadOnly(True)
        comm_layout.addWidget(self.comm_text, stretch=1)

        self.tabs.addTab(comm_tab, "通信数据")

        gtp_tab = QWidget()
        gtp_layout = QVBoxLayout(gtp_tab)
        gtp_layout.setContentsMargins(2, 2, 2, 2)
        gtp_layout.setSpacing(2)

        gtp_ctrl = QHBoxLayout()
        gtp_ctrl.addStretch()
        btn_clear_gtp = QPushButton("清空")
        btn_clear_gtp.clicked.connect(self._clear_gtp)
        gtp_ctrl.addWidget(btn_clear_gtp)
        gtp_layout.addLayout(gtp_ctrl)

        self.gtp_text = QTextEdit()
        self.gtp_text.setReadOnly(True)
        gtp_layout.addWidget(self.gtp_text, stretch=1)

        self.tabs.addTab(gtp_tab, "GTP 输出")

        board_tab = QWidget()
        board_layout = QVBoxLayout(board_tab)
        board_layout.setContentsMargins(4, 4, 4, 4)
        board_layout.setSpacing(4)

        ctrl = QHBoxLayout()
        self.show_cand_check = QCheckBox("显示选点")
        self.show_cand_check.setChecked(True)
        self.show_cand_check.stateChanged.connect(self._on_show_cand_change)
        ctrl.addWidget(self.show_cand_check)
        ctrl.addStretch()
        board_layout.addLayout(ctrl)

        self.board_view = BoardView()
        self.board_view.set_max_candidates(10)
        board_layout.addWidget(self.board_view, stretch=1)

        self.tabs.addTab(board_tab, "实时棋盘")

        winrate_tab = QWidget()
        winrate_layout = QVBoxLayout(winrate_tab)
        winrate_layout.setContentsMargins(4, 4, 4, 4)
        winrate_layout.setSpacing(4)

        wr_ctrl = QHBoxLayout()
        btn_clear_wr = QPushButton("清空曲线")
        btn_clear_wr.clicked.connect(self._clear_winrate_curve)
        wr_ctrl.addWidget(btn_clear_wr)

        btn_export_wr = QPushButton("导出图片")
        btn_export_wr.clicked.connect(self._export_winrate_image)
        wr_ctrl.addWidget(btn_export_wr)

        btn_detach_wr = QPushButton("独立窗口")
        btn_detach_wr.clicked.connect(self._detach_winrate)
        wr_ctrl.addWidget(btn_detach_wr)

        wr_ctrl.addStretch()
        winrate_layout.addLayout(wr_ctrl)

        self.winrate_view = WinrateView()
        winrate_layout.addWidget(self.winrate_view, stretch=1)

        self.tabs.addTab(winrate_tab, "胜率曲线")

        main_layout.addWidget(left_scroll, stretch=1)
        main_layout.addWidget(self.tabs, stretch=1)

    def _connect_signals(self):
        self.comm_signal.connect(self._append_comm)
        self.gtp_signal.connect(self._append_gtp)
        self.candidate_signal.connect(self._on_candidate)
        self.board_signal.connect(self._do_update_board)
        self.engine_exit_signal.connect(self._stop_engine)

    def _switch_mode(self, mode):
        self.cfg["engine_mode"] = mode
        save_config(self.cfg)
        if mode == "local":
            self.mode_stack.setCurrentIndex(0)
        else:
            self.mode_stack.setCurrentIndex(1)

    def _browse_engine(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 AI 引擎")
        if path:
            self.engine_combo.setCurrentText(path)
            self._auto_gen_cmd()

    def _browse_weight(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择权重文件")
        if path:
            self.weight_combo.setCurrentText(path)
            self._auto_gen_cmd()

    def _browse_config(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择配置文件")
        if path:
            self.config_combo.setCurrentText(path)
            self._auto_gen_cmd()

    def _browse_ssh_key(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择私钥文件")
        if path:
            self.ssh_key_edit.setText(path)

    def _auto_gen_cmd(self):
        engine = self.engine_combo.currentText().strip()
        weight = self.weight_combo.currentText().strip()
        config = self.config_combo.currentText().strip()
        if not engine:
            return
        name = os.path.basename(engine).lower()
        if "katago" in name:
            parts = [f'"{engine}"', "gtp"]
            if weight:
                parts.append(f'-model "{weight}"')
            if config:
                parts.append(f'-config "{config}"')
        else:
            parts = [f'"{engine}"', "--gtp", "--quiet", "--noponder"]
            if weight:
                parts.append(f'-w "{weight}"')
            if config:
                parts.append(f'--config "{config}"')
        self.comm_cmd_edit.setText(" ".join(parts))

    def _check_cmd_match(self, cmd, engine, weight, config):
        if not engine:
            return True, ""
        if not cmd:
            return False, "命令行为空"

        cmd_lower = cmd.lower().replace('"', '')
        engine_lower = engine.lower().replace('"', '')
        engine_name = os.path.basename(engine_lower)

        if engine_lower not in cmd_lower and engine_name not in cmd_lower:
            return False, f"命令行里没有引擎: {engine}"

        if weight:
            weight_name = os.path.basename(weight.lower())
            if weight.lower() not in cmd_lower and weight_name not in cmd_lower:
                return False, f"命令行里没有权重: {weight}"

        if config:
            config_name = os.path.basename(config.lower())
            if config.lower() not in cmd_lower and config_name not in cmd_lower:
                return False, f"命令行里没有配置: {config}"

        return True, ""

    def _start_engine(self):
        engine_path = self.engine_combo.currentText().strip()
        weight_path = self.weight_combo.currentText().strip()
        config_path = self.config_combo.currentText().strip()
        comm_cmd = self.comm_cmd_edit.text().strip()

        if not comm_cmd:
            self._auto_gen_cmd()
            comm_cmd = self.comm_cmd_edit.text().strip()

        ok, msg = self._check_cmd_match(comm_cmd, engine_path, weight_path, config_path)
        if not ok:
            QMessageBox.warning(self, "命令行不匹配", msg)
            return

        if comm_cmd:
            ok, msg = self.engine.start("", "", "", "", remote_cmd=comm_cmd)
        else:
            ok, msg = self.engine.start(engine_path, weight_path, config_path, "")

        self._log_comm(msg)
        if not ok:
            self._stop_engine()
            return

        if not comm_cmd and config_path:
            cfg_vals = self._load_gtp_cfg(config_path)
            if "max_time" in cfg_vals:
                self.max_time_edit.setText(cfg_vals["max_time"])
            if "max_visits" in cfg_vals:
                self.max_visits_edit.setText(cfg_vals["max_visits"])
            if "max_playouts" in cfg_vals:
                self.max_playouts_edit.setText(cfg_vals["max_playouts"])

        self._on_live_winrate_change(self.live_winrate_check.checkState())

        if engine_path:
            push_history(self.cfg, "engine_history", engine_path)
        if weight_path:
            push_history(self.cfg, "weight_history", weight_path)
        if config_path:
            push_history(self.cfg, "config_history", config_path)

        self.engine_combo.clear()
        self.engine_combo.addItems(self.cfg["engine_history"])
        self.engine_combo.setCurrentText(engine_path)

        self.weight_combo.clear()
        self.weight_combo.addItems(self.cfg["weight_history"])
        self.weight_combo.setCurrentText(weight_path)

        self.config_combo.clear()
        self.config_combo.addItems(self.cfg["config_history"])
        self.config_combo.setCurrentText(config_path)

        save_config(self.cfg)

        self.btn_start_engine.setEnabled(False)
        self.btn_stop_engine.setEnabled(True)
        self.btn_start_ssh.setEnabled(False)
        self.btn_stop_ssh.setEnabled(False)
        self.btn_mode_local.setEnabled(False)
        self.btn_mode_ssh.setEnabled(False)
        self._lock_browse(True)

    def _start_ssh(self):
        host = self.ssh_host_edit.text().strip()
        port = self.ssh_port_edit.text().strip() or "22"
        user = self.ssh_user_edit.text().strip()
        password = self.ssh_pass_edit.text()
        key_file = self.ssh_key_edit.text().strip()
        command = self.ssh_cmd_edit.text().strip()

        if not host or not user or not command:
            QMessageBox.warning(self, "SSH", "主机、用户名、命令都不能为空")
            return

        ok, msg = self.engine.start_ssh(host, port, user, password, key_file, command)
        self._log_comm(msg)
        if not ok:
            self._stop_engine()
            return

        self.btn_start_ssh.setEnabled(False)
        self.btn_stop_ssh.setEnabled(True)
        self.btn_start_engine.setEnabled(False)
        self.btn_stop_engine.setEnabled(False)
        self.btn_mode_local.setEnabled(False)
        self.btn_mode_ssh.setEnabled(False)

    def _stop_engine(self):
        self.engine.stop()
        self._log_comm("引擎已停止")
        self.btn_start_engine.setEnabled(True)
        self.btn_stop_engine.setEnabled(False)
        self.btn_start_ssh.setEnabled(True)
        self.btn_stop_ssh.setEnabled(False)

        if self.fox.is_connected() if hasattr(self.fox, "is_connected") else False:
            self.btn_start_fox_local.setEnabled(False)
            self.btn_stop_fox_local.setEnabled(True)
            self.btn_start_fox_ssh.setEnabled(False)
            self.btn_stop_fox_ssh.setEnabled(True)
            self.btn_mode_local.setEnabled(False)
            self.btn_mode_ssh.setEnabled(False)
        else:
            self.btn_start_fox_local.setEnabled(True)
            self.btn_stop_fox_local.setEnabled(False)
            self.btn_start_fox_ssh.setEnabled(True)
            self.btn_stop_fox_ssh.setEnabled(False)
            self.btn_mode_local.setEnabled(True)
            self.btn_mode_ssh.setEnabled(True)

        self._lock_browse(False)

    def _lock_browse(self, locked):
        for btn in [self.btn_browse_engine, self.btn_browse_weight, self.btn_browse_config]:
            btn.setEnabled(not locked)
        self.comm_cmd_edit.setEnabled(not locked)

    def _on_engine_exit_signal(self):
        self.engine_exit_signal.emit()

    # ---------- 自动跑谱 ----------
    def _idle_loop(self):
        while True:
            time.sleep(10)
            # 大前提 1：必须启用自动跑谱
            if not self.cfg.get("auto_contribute", False):
                continue
            # 大前提 2：跑谱命令不能为空
            if not self.cfg.get("contribute_command", "").strip():
                continue
            # 大前提 3：主对弈引擎必须已经启动
            if not self.engine.is_running():
                # 引擎没启动，如果跑谱还在跑，立刻停掉
                if self.runner.is_running():
                    self._stop_contribute()
                continue
            # 大前提 4：必须已经开启监听野狐客户端
            if not self.fox.is_listening():
                if self.runner.is_running():
                    self._stop_contribute()
                continue
            # 大前提 5：当前不能正在对局
            if self.bridge.last_move_number > 0:
                if self.runner.is_running():
                    self._stop_contribute()
                continue
            # 如果跑谱已经在跑，不重复启动
            if self.runner.is_running():
                continue
            # 空闲时间判断
            idle = time.time() - self._last_game_time
            threshold = self.cfg.get("contribute_idle_seconds", 300)
            if idle >= threshold:
                self._start_contribute()

    def _start_contribute(self):
        if self.runner.is_running():
            self._stop_contribute()
        cmd = self.cfg.get("contribute_command", "").strip()
        if not cmd:
            return
        ok, msg = self.runner.start(cmd)
        self._log_comm(msg)
        if ok:
            self.contribute_label.setText("运行中")
            self.btn_stop_contribute.setEnabled(True)

    def _stop_contribute(self):
        """只停止跑谱进程，不动配置，用于对局开始/引擎停止时"""
        if self.runner.is_running():
            self.runner.stop()
            self._log_comm("跑谱已停止")
        self.contribute_label.setText("未运行")
        self.btn_stop_contribute.setEnabled(False)

    def _manual_stop_contribute(self):
        """用户手动点击停止跑谱，停止并关闭自动跑谱"""
        self._stop_contribute()
        self.cfg["auto_contribute"] = False
        save_config(self.cfg)
        self._log_comm("已手动停止跑谱，并关闭自动跑谱")

    def _port_in_use(self, port):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("0.0.0.0", port))
            s.close()
            return False
        except OSError:
            return True

    def _start_fox(self):
        try:
            port = int(self.fox_port_edit.text())
        except ValueError:
            self._log_comm("端口无效")
            return

        if self._port_in_use(port):
            QMessageBox.warning(self, "端口竞争", f"端口 {port} 已被占用。")
            return

        ok, msg = self.fox.start(port)
        self._log_comm(msg)
        if ok:
            self.btn_start_fox_local.setEnabled(False)
            self.btn_stop_fox_local.setEnabled(True)
            self.btn_start_fox_ssh.setEnabled(False)
            self.btn_stop_fox_ssh.setEnabled(True)
            self.btn_start_engine.setEnabled(False)
            self.btn_stop_engine.setEnabled(False)
            self.btn_start_ssh.setEnabled(False)
            self.btn_stop_ssh.setEnabled(False)
            self.btn_mode_local.setEnabled(False)
            self.btn_mode_ssh.setEnabled(False)

    def _start_fox_ssh(self):
        try:
            port = int(self.ssh_fox_port_edit.text())
        except ValueError:
            self._log_comm("端口无效")
            return

        if self._port_in_use(port):
            QMessageBox.warning(self, "端口竞争", f"端口 {port} 已被占用。")
            return

        ok, msg = self.fox.start(port)
        self._log_comm(msg)
        if ok:
            self.btn_start_fox_local.setEnabled(False)
            self.btn_stop_fox_local.setEnabled(True)
            self.btn_start_fox_ssh.setEnabled(False)
            self.btn_stop_fox_ssh.setEnabled(True)
            self.btn_start_engine.setEnabled(False)
            self.btn_stop_engine.setEnabled(False)
            self.btn_start_ssh.setEnabled(False)
            self.btn_stop_ssh.setEnabled(False)
            self.btn_mode_local.setEnabled(False)
            self.btn_mode_ssh.setEnabled(False)

    def _stop_fox(self):
        self.fox.stop()
        self._last_game_time = time.time()
        self._log_comm("野狐监听已停止")
        self.btn_start_fox_local.setEnabled(True)
        self.btn_stop_fox_local.setEnabled(False)
        self.btn_start_fox_ssh.setEnabled(True)
        self.btn_stop_fox_ssh.setEnabled(False)

        if self.engine.is_running():
            self.btn_start_engine.setEnabled(False)
            self.btn_stop_engine.setEnabled(True)
            self.btn_start_ssh.setEnabled(False)
            self.btn_stop_ssh.setEnabled(True)
            self.btn_mode_local.setEnabled(False)
            self.btn_mode_ssh.setEnabled(False)
        else:
            self.btn_start_engine.setEnabled(True)
            self.btn_stop_engine.setEnabled(False)
            self.btn_start_ssh.setEnabled(True)
            self.btn_stop_ssh.setEnabled(False)
            self.btn_mode_local.setEnabled(True)
            self.btn_mode_ssh.setEnabled(True)

    def _send_rule(self, rule):
        if not self.engine.is_running():
            self._log_gtp("引擎未运行，无法切换规则")
            return
        self.bridge.set_rules(rule)
        self._log_gtp(f"已切换规则: {rule}")

    def _on_fox_command(self, command, items):
        self._last_game_time = time.time()
        if self.cfg.get("contribute_stop_on_game", True):
            if self.runner.is_running():
                self._stop_contribute()
        self.bridge.handle_fox_command(command, items)
        if command == "FARESULT":
            self.board_view.clear()
            self.winrate_view.clear()
            if self.winrate_window is not None and self._detached_view is not None:
                self._detached_view.clear()
        else:
            self.board_signal.emit()

    def _on_fox_reconnect(self):
        self._log_comm("野狐客户端断开，等待重连...")
        self.board_view.clear()
        self.winrate_view.clear()
        if self.winrate_window is not None and self._detached_view is not None:
            self._detached_view.clear()

    def _on_engine_output(self, line):
        self.bridge.on_engine_output(line)
        self._update_winrate_curve(line)

    def _on_engine_raw(self, line):
        self.gtp_signal.emit(line)

    def _on_candidate(self, candidates):
        self.board_view.set_candidates(candidates)

    def _update_winrate_curve(self, line):
        stripped = line.strip()
        if "MALKOVICH" in stripped and "Winrate" in stripped:
            m = re.search(r"Winrate\s+([\d.]+)%", stripped)
            if m:
                winrate = float(m.group(1)) / 100.0
                ai_color = self.bridge.ai_color
                if ai_color == "B":
                    black_wr = winrate
                else:
                    black_wr = 1.0 - winrate
                move_num = self.bridge.last_move_number
                self.winrate_view.add_point(move_num, black_wr)
                if self.winrate_window is not None and self._detached_view is not None:
                    self._detached_view.add_point(move_num, black_wr)

            m = re.search(r"ScoreLead\s+(-?[\d.]+)", stripped)
            if m:
                score_lead = float(m.group(1))
                own_score = score_lead
                move_num = self.bridge.last_move_number
                self.winrate_view.add_score(move_num, own_score)
                if self.winrate_window is not None and self._detached_view is not None:
                    self._detached_view.add_score(move_num, own_score)

            m = re.search(r"ScoreStdev\s+([\d.]+)", stripped)
            if m:
                stdev = float(m.group(1))
                self.winrate_view.set_stdev(stdev)
                if self.winrate_window is not None and self._detached_view is not None:
                    self._detached_view.set_stdev(stdev)

    def _on_live_winrate_change(self, state):
        enabled = bool(state)
        self.bridge.set_live_winrate(enabled)
        self.winrate_param_widget.setVisible(enabled)

        try:
            self.bridge.set_max_time(float(self.max_time_edit.text()))
        except ValueError:
            pass
        try:
            self.bridge.set_max_visits(int(self.max_visits_edit.text()))
        except ValueError:
            pass
        try:
            self.bridge.set_max_playouts(int(self.max_playouts_edit.text()))
        except ValueError:
            pass

    def _refresh_state(self):
        try:
            self.bridge.set_max_time(float(self.max_time_edit.text()))
        except ValueError:
            pass
        try:
            self.bridge.set_max_visits(int(self.max_visits_edit.text()))
        except ValueError:
            pass
        try:
            self.bridge.set_max_playouts(int(self.max_playouts_edit.text()))
        except ValueError:
            pass
        self._log_comm("参数已刷新")

    def _do_update_board(self):
        stones = {}
        for n, (color, vertex) in self.bridge.fox_moves.items():
            v = self.bridge._gtp_to_xy(vertex)
            if v:
                stones[n] = (color, v[0], v[1])
        self.board_view.set_stones(stones)
        if stones:
            last_n = max(stones.keys())
            self.board_view.set_last_move(stones[last_n])

    def _on_show_cand_change(self, state):
        self.board_view.set_show_candidates(bool(state))

    def _clear_winrate_curve(self):
        self.winrate_view.clear()
        if self.winrate_window is not None and self._detached_view is not None:
            self._detached_view.clear()

    def _export_winrate_image(self):
        ok, msg = self.winrate_view.export_image(self)
        self._log_comm(msg)
        if ok:
            QMessageBox.information(self, "导出成功", msg)
        else:
            QMessageBox.warning(self, "导出失败", msg)

    def _detach_winrate(self):
        if self.winrate_window is not None:
            self.winrate_window.show()
            self.winrate_window.raise_()
            return

        dlg = QDialog(None)
        dlg.setWindowTitle("胜率曲线")
        dlg.resize(800, 500)

        dlg.setWindowFlags(
            Qt.Window |
            Qt.WindowMinimizeButtonHint |
            Qt.WindowMaximizeButtonHint |
            Qt.WindowCloseButtonHint
        )

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(4, 4, 4, 4)

        chk_top = QCheckBox("总在最前")
        chk_top.setChecked(False)
        chk_top.stateChanged.connect(
            lambda state: self._set_winrate_always_on_top(dlg, bool(state))
        )
        layout.addWidget(chk_top)

        view = WinrateView()
        self._detached_view = view
        layout.addWidget(view, stretch=1)

        for m, wr in self.winrate_view.data:
            view.add_point(m, wr)
        for m, s in self.winrate_view.score_data:
            view.add_score(m, s)

        if self.winrate_view.stdev is not None:
            view.set_stdev(self.winrate_view.stdev)

        if self.cfg.get("dark_winrate_bg", False):
            view.set_dark_mode(True)

        dlg.setLayout(layout)
        dlg.finished.connect(self._on_winrate_window_closed)

        self.winrate_window = dlg
        dlg.show()

    def _set_winrate_always_on_top(self, dlg, always_on_top):
        flags = dlg.windowFlags()
        if always_on_top:
            dlg.setWindowFlags(flags | Qt.WindowStaysOnTopHint)
        else:
            dlg.setWindowFlags(flags & ~Qt.WindowStaysOnTopHint)
        dlg.show()

    def _on_winrate_window_closed(self):
        self.winrate_window = None
        self._detached_view = None

    def _send_shell(self):
        cmd = self.shell_edit.text().strip()
        if not cmd:
            return
        if not self.engine.is_running():
            self._log_gtp("引擎未运行")
            return
        for line in cmd.splitlines():
            line = line.strip()
            if not line:
                continue
            self.engine.send(line)
            self._log_gtp(f">>> {line}")
        self.shell_edit.clear()

    def _on_snippet_selected(self, text):
        if not text or text == "（无）":
            return
        self.shell_edit.setText(text)

    def _refresh_snippet_combo(self):
        self.snippet_combo.clear()
        self.snippet_combo.addItem("（无）")
        for s in self.cfg.get("gtp_snippets", []):
            self.snippet_combo.addItem(s)

    def _manage_snippets(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("管理常用 GTP 指令")
        dlg.resize(600, 400)

        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("指令列表（每条一行）:"))

        self._snippet_list = QListWidget()
        for s in self.cfg.get("gtp_snippets", []):
            self._snippet_list.addItem(s)
        layout.addWidget(self._snippet_list, stretch=1)

        edit_row = QHBoxLayout()
        self._snippet_edit = QLineEdit()
        self._snippet_edit.setPlaceholderText("输入一条 GTP 命令，例如 kata-set-param maxTime 5")
        edit_row.addWidget(self._snippet_edit, stretch=1)

        btn_add = QPushButton("添加")
        btn_add.clicked.connect(self._snippet_add)
        edit_row.addWidget(btn_add)
        layout.addLayout(edit_row)

        btn_row = QHBoxLayout()
        btn_del = QPushButton("删除选中")
        btn_del.clicked.connect(self._snippet_delete)
        btn_row.addWidget(btn_del)
        btn_row.addStretch()
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        dlg.exec_()

    def _snippet_add(self):
        text = self._snippet_edit.text().strip()
        if not text:
            return
        snippets = self.cfg.get("gtp_snippets", [])
        if not isinstance(snippets, list):
            snippets = []
        if text not in snippets:
            snippets.append(text)
            self.cfg["gtp_snippets"] = snippets
            save_config(self.cfg)
            self._snippet_list.addItem(text)
            self._refresh_snippet_combo()
        self._snippet_edit.clear()

    def _snippet_delete(self):
        item = self._snippet_list.currentItem()
        if not item:
            return
        text = item.text()
        snippets = self.cfg.get("gtp_snippets", [])
        if not isinstance(snippets, list):
            snippets = []
        if text in snippets:
            snippets.remove(text)
            self.cfg["gtp_snippets"] = snippets
            save_config(self.cfg)
            self._snippet_list.takeItem(self._snippet_list.row(item))
            self._refresh_snippet_combo()

    # ---------- 视图菜单 ----------
    def _open_bg_color_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("界面背景色")
        dlg.resize(400, 150)

        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("拖动色条调整界面背景:"))

        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        bg_color = self.cfg.get("bg_color", "#F0F0F0")
        try:
            c = QColor(bg_color)
            lum = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
            slider.setValue(max(0, min(100, int(lum * 100 / 255))))
        except Exception:
            slider.setValue(20)
        layout.addWidget(slider)

        preview = QLabel()
        preview.setFixedSize(60, 30)
        preview.setStyleSheet(
            f"background-color: {bg_color}; border: 1px solid #888;"
        )
        layout.addWidget(preview)

        def on_change(value):
            colors = [
                (40, 40, 40),
                (100, 100, 100),
                (235, 235, 235),
                (232, 196, 138),
                (200, 220, 240),
                (200, 235, 200),
                (230, 210, 240),
            ]
            n = len(colors) - 1
            idx = value * n / 100
            i = int(idx)
            if i >= n:
                i = n - 1
            t = idx - i
            r = int(colors[i][0] * (1 - t) + colors[i + 1][0] * t)
            g = int(colors[i][1] * (1 - t) + colors[i + 1][1] * t)
            b = int(colors[i][2] * (1 - t) + colors[i + 1][2] * t)
            color = QColor(r, g, b)
            preview.setStyleSheet(
                f"background-color: {color.name()}; border: 1px solid #888;"
            )
            self._apply_bg_color(color.name())

        slider.valueChanged.connect(on_change)

        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(dlg.accept)
        layout.addWidget(btn_close)

        dlg.exec_()

    def _toggle_dark_winrate(self):
        current = self.cfg.get("dark_winrate_bg", False)
        new = not current
        self.cfg["dark_winrate_bg"] = new
        save_config(self.cfg)
        self.winrate_view.set_dark_mode(new)
        if self.winrate_window is not None and self._detached_view is not None:
            self._detached_view.set_dark_mode(new)

    def _toggle_dark_board(self):
        current = self.cfg.get("dark_board_bg", False)
        new = not current
        self.cfg["dark_board_bg"] = new
        save_config(self.cfg)
        self.board_view.set_dark_mode(new)

    def _apply_bg_color(self, color_hex):
        try:
            c = QColor(color_hex)
            if not c.isValid():
                return
        except Exception:
            return

        r, g, b = c.red(), c.green(), c.blue()
        luminance = 0.299 * r + 0.587 * g + 0.114 * b
        if luminance > 128:
            text_color = "#222222"
            placeholder_color = "#888888"
            border_color = "#CCCCCC"
            btn_bg = "#E8E8E8"
            btn_hover = "#D8D8D8"
            btn_pressed = "#C0C0C0"
            btn_disabled_bg = "#D0D0D0"
            btn_disabled_fg = "#A0A0A0"
            btn_disabled_border = "#D0D0D0"
        else:
            text_color = "#EEEEEE"
            placeholder_color = "#AAAAAA"
            border_color = "#555555"
            btn_bg = "#4A4A4A"
            btn_hover = "#5A5A5A"
            btn_pressed = "#3A3A3A"
            btn_disabled_bg = "#3A3A3A"
            btn_disabled_fg = "#666666"
            btn_disabled_border = "#3A3A3A"

        self.setStyleSheet(
            f"QMainWindow {{ background-color: {color_hex}; }}"
            f"QWidget {{ background-color: {color_hex}; color: {text_color}; }}"
            f"QScrollArea {{ background-color: {color_hex}; border: none; }}"
            f"QScrollArea > QWidget > QWidget {{ background-color: {color_hex}; }}"
            f"QScrollArea > QWidget > QScrollBar {{ background-color: {color_hex}; }}"
            f"QLabel {{ color: {text_color}; background: transparent; }}"
            f"QGroupBox {{ color: {text_color}; border: 1px solid {border_color}; "
            f"  margin-top: 8px; padding-top: 8px; border-radius: 4px; }}"
            f"QGroupBox::title {{ color: {text_color}; subcontrol-origin: margin; "
            f"  left: 8px; padding: 0 4px; }}"
            f"QCheckBox {{ color: {text_color}; background: transparent; }}"
            f"QComboBox {{ min-height: 34px; padding: 4px 8px; "
            f"  background-color: {btn_bg}; color: {text_color}; "
            f"  border: 1px solid {border_color}; border-radius: 4px; }}"
            f"QComboBox:hover {{ background-color: {btn_hover}; }}"
            f"QComboBox:disabled {{ background-color: {btn_disabled_bg}; "
            f"  color: {btn_disabled_fg}; border: 1px solid {btn_disabled_border}; }}"
            f"QLineEdit {{ min-height: 34px; padding: 4px 8px; "
            f"  background-color: {btn_bg}; color: {text_color}; "
            f"  border: 1px solid {border_color}; border-radius: 4px; }}"
            f"QLineEdit:disabled {{ background-color: {btn_disabled_bg}; "
            f"  color: {btn_disabled_fg}; border: 1px solid {btn_disabled_border}; }}"
            f"QPushButton {{ min-height: 30px; padding: 4px 12px; "
            f"  background-color: {btn_bg}; color: {text_color}; "
            f"  border: 1px solid {border_color}; border-radius: 4px; }}"
            f"QPushButton:hover {{ background-color: {btn_hover}; }}"
            f"QPushButton:pressed {{ background-color: {btn_pressed}; }}"
            f"QPushButton:disabled {{ background-color: {btn_disabled_bg}; "
            f"  color: {btn_disabled_fg}; "
            f"  border: 1px solid {btn_disabled_border}; }}"
            f"QTabWidget::pane {{ border: 1px solid {border_color}; }}"
            f"QTabBar::tab {{ background: {border_color}; color: {text_color}; "
            f"  padding: 6px 12px; }}"
            f"QTabBar::tab:selected {{ background: {color_hex}; }}"
        )

        palette = self.palette()
        palette.setColor(QPalette.PlaceholderText, QColor(placeholder_color))
        self.setPalette(palette)

        self.cfg["bg_color"] = color_hex
        save_config(self.cfg)

    # ---------- 心跳 / 重连 / Token 对话框 ----------
    def _open_heartbeat_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("心跳设置")
        dlg.resize(400, 200)

        layout = QFormLayout(dlg)

        chk = QCheckBox("启用心跳检测")
        chk.setChecked(self.cfg.get("heartbeat_enabled", False))
        layout.addRow("", chk)

        interval_edit = QLineEdit(str(self.cfg.get("heartbeat_interval", 30)))
        layout.addRow("心跳间隔（秒）:", interval_edit)

        timeout_edit = QLineEdit(str(self.cfg.get("heartbeat_timeout", 10)))
        layout.addRow("超时判定（秒）:", timeout_edit)

        def on_save():
            self.cfg["heartbeat_enabled"] = chk.isChecked()
            try:
                self.cfg["heartbeat_interval"] = int(interval_edit.text())
            except ValueError:
                self.cfg["heartbeat_interval"] = 30
            try:
                self.cfg["heartbeat_timeout"] = int(timeout_edit.text())
            except ValueError:
                self.cfg["heartbeat_timeout"] = 10
            save_config(self.cfg)
            self.engine.set_heartbeat(
                self.cfg["heartbeat_enabled"],
                self.cfg["heartbeat_interval"],
                self.cfg["heartbeat_timeout"],
            )
            self._log_comm("心跳设置已保存")
            dlg.accept()

        btn = QPushButton("保存")
        btn.clicked.connect(on_save)
        layout.addRow("", btn)

        dlg.exec_()

    def _open_reconnect_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("断线重连设置")
        dlg.resize(400, 200)

        layout = QFormLayout(dlg)

        chk = QCheckBox("启用自动重连")
        chk.setChecked(self.cfg.get("auto_reconnect", True))
        layout.addRow("", chk)

        interval_edit = QLineEdit(str(self.cfg.get("reconnect_interval", 5)))
        layout.addRow("重连间隔（秒）:", interval_edit)

        def on_save():
            self.cfg["auto_reconnect"] = chk.isChecked()
            try:
                self.cfg["reconnect_interval"] = int(interval_edit.text())
            except ValueError:
                self.cfg["reconnect_interval"] = 5
            save_config(self.cfg)
            self.fox.set_auto_reconnect(
                self.cfg["auto_reconnect"],
                self.cfg["reconnect_interval"],
            )
            self._log_comm("断线重连设置已保存")
            dlg.accept()

        btn = QPushButton("保存")
        btn.clicked.connect(on_save)
        layout.addRow("", btn)

        dlg.exec_()

    def _open_token_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("API Token 设置")
        dlg.resize(500, 200)

        layout = QFormLayout(dlg)

        chk = QCheckBox("启用 Token 认证")
        chk.setChecked(self.cfg.get("api_token_enabled", False))
        layout.addRow("", chk)

        token_edit = QLineEdit(self.cfg.get("api_token", ""))
        token_edit.setPlaceholderText("留空则自动生成")
        layout.addRow("Token:", token_edit)

        def on_generate():
            token_edit.setText("sakura_" + secrets.token_hex(16))

        btn_gen = QPushButton("自动生成")
        btn_gen.clicked.connect(on_generate)
        layout.addRow("", btn_gen)

        def on_save():
            self.cfg["api_token_enabled"] = chk.isChecked()
            token = token_edit.text().strip()
            if not token and self.cfg["api_token_enabled"]:
                token = "sakura_" + secrets.token_hex(16)
                token_edit.setText(token)
            self.cfg["api_token"] = token
            save_config(self.cfg)
            self.api_server.set_token(self.cfg["api_token_enabled"], token)
            QMessageBox.information(dlg, "Token", f"当前 Token:\n{token}")
            dlg.accept()

        btn = QPushButton("保存")
        btn.clicked.connect(on_save)
        layout.addRow("", btn)

        dlg.exec_()

    # ---------- HTTP API ----------
    def _open_api_window(self):
        if self.api_window is not None:
            self.api_window.show()
            self.api_window.raise_()
            return

        dlg = QDialog(None)
        dlg.setWindowTitle("HTTP API")
        dlg.resize(500, 300)

        dlg.setWindowFlags(
            Qt.Window |
            Qt.WindowMinimizeButtonHint |
            Qt.WindowMaximizeButtonHint |
            Qt.WindowCloseButtonHint
        )

        layout = QVBoxLayout(dlg)

        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("端口:"))
        api_port_edit = QLineEdit(str(self.cfg.get("api_port", 8765)))
        api_port_edit.setFixedWidth(80)
        ctrl.addWidget(api_port_edit)

        btn_start = QPushButton("启动 API")
        btn_stop = QPushButton("停止 API")
        ctrl.addWidget(btn_start)
        ctrl.addWidget(btn_stop)
        ctrl.addStretch()
        layout.addLayout(ctrl)

        doc_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "SakuraGTP HTTP API 文档.md"
        )
        if os.path.exists(doc_path):
            link = QLabel(
                f'<a href="file:///{doc_path}" '
                f'style="color: #2A6FDB; text-decoration: underline; font-size: 14pt;">'
                f'点击查看 / 下载 API 文档</a>'
            )
        else:
            link = QLabel("未找到 API 文档")
        link.setOpenExternalLinks(True)
        layout.addWidget(link)

        layout.addStretch()

        def on_start():
            try:
                port = int(api_port_edit.text())
            except ValueError:
                QMessageBox.warning(dlg, "错误", "端口无效")
                return
            self.api_server.host = "127.0.0.1"
            self.api_server.port = port
            ok, msg = self.api_server.start()
            self._log_comm(msg)
            if ok:
                btn_start.setEnabled(False)
                btn_stop.setEnabled(True)
                self.cfg["api_port"] = port
                self.cfg["api_enabled"] = True
                save_config(self.cfg)

        def on_stop():
            self.api_server.stop()
            btn_start.setEnabled(True)
            btn_stop.setEnabled(False)
            self.cfg["api_enabled"] = False
            save_config(self.cfg)

        btn_start.clicked.connect(on_start)
        btn_stop.clicked.connect(on_stop)

        if self.api_server.is_running():
            btn_start.setEnabled(False)
            btn_stop.setEnabled(True)
        else:
            btn_stop.setEnabled(False)

        dlg.finished.connect(lambda: self._on_api_window_closed())
        self.api_window = dlg
        dlg.show()

    def _open_contribute_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("自动跑谱设置")
        dlg.resize(600, 300)

        layout = QFormLayout(dlg)

        chk = QCheckBox("启用自动跑谱")
        chk.setChecked(self.cfg.get("auto_contribute", False))
        layout.addRow("", chk)

        cmd_edit = QLineEdit(self.cfg.get("contribute_command", ""))
        cmd_edit.setPlaceholderText(
            'katago.exe contribute -config contribute_example.cfg'
        )
        layout.addRow("跑谱命令:", cmd_edit)

        idle_edit = QLineEdit(str(self.cfg.get("contribute_idle_seconds", 300)))
        layout.addRow("空闲多少秒后启动:", idle_edit)

        stop_chk = QCheckBox("有对局立刻停止跑谱")
        stop_chk.setChecked(self.cfg.get("contribute_stop_on_game", True))
        layout.addRow("", stop_chk)

        hint = QLabel(
            "提示：\n"
            "1. 跑谱命令需要用户自备能跑谱的 KataGo 引擎和 contribute 配置文件。\n"
            "2. 示例：katago.exe contribute -config contribute_example.cfg\n"
            "3. contribute 配置里需要填 username、password。\n"
            "4. 跑谱进程独立于对弈引擎，不冲突。"
        )
        hint.setWordWrap(True)
        layout.addRow("", hint)

        def on_save():
            self.cfg["auto_contribute"] = chk.isChecked()
            self.cfg["contribute_command"] = cmd_edit.text().strip()
            try:
                self.cfg["contribute_idle_seconds"] = int(idle_edit.text())
            except ValueError:
                self.cfg["contribute_idle_seconds"] = 300
            self.cfg["contribute_stop_on_game"] = stop_chk.isChecked()
            save_config(self.cfg)
            self._log_comm("自动跑谱设置已保存")
            dlg.accept()

        btn = QPushButton("保存")
        btn.clicked.connect(on_save)
        layout.addRow("", btn)

        dlg.exec_()

    def _on_api_window_closed(self):
        self.api_window = None

    # ---------- 配置 ----------
    def _collect_cfg(self):
        self.cfg["engine_path"] = self.engine_combo.currentText()
        self.cfg["weight_path"] = self.weight_combo.currentText()
        self.cfg["config_path"] = self.config_combo.currentText()
        self.cfg["comm_cmd"] = self.comm_cmd_edit.text()
        try:
            self.cfg["fox_listen_port"] = int(self.fox_port_edit.text())
        except ValueError:
            pass
        try:
            self.cfg["max_time"] = float(self.max_time_edit.text())
        except ValueError:
            pass
        try:
            self.cfg["max_visits"] = int(self.max_visits_edit.text())
        except ValueError:
            pass
        try:
            self.cfg["max_playouts"] = int(self.max_playouts_edit.text())
        except ValueError:
            pass
        self.cfg["ssh_host"] = self.ssh_host_edit.text()
        self.cfg["ssh_port"] = self.ssh_port_edit.text()
        self.cfg["ssh_user"] = self.ssh_user_edit.text()
        self.cfg["ssh_key"] = self.ssh_key_edit.text()
        self.cfg["ssh_cmd"] = self.ssh_cmd_edit.text()

    def _save_cfg(self):
        self._collect_cfg()
        save_config(self.cfg)
        QMessageBox.information(self, "SakuraGTP", "配置已保存")

    def _load_gtp_cfg(self, config_path):
        result = {}
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if not s or s.startswith("#"):
                        continue
                    if "=" not in s:
                        continue
                    key, val = s.split("=", 1)
                    key = key.strip()
                    val = val.strip()
                    if key == "maxTime":
                        result["max_time"] = val
                    elif key == "maxVisits":
                        result["max_visits"] = val
                    elif key == "maxPlayouts":
                        result["max_playouts"] = val
        except Exception:
            pass
        return result

    # ---------- API 回调 ----------
    def _api_status(self):
        return {
            "engine_running": self.engine.is_running(),
            "fox_listening": self.fox.is_connected() if hasattr(self.fox, "is_connected") else False,
            "api_running": self.api_server.is_running() if self.api_server else False,
            "ai_color": self.bridge.ai_color,
            "board_size": self.bridge.board_size,
            "komi": self.bridge.komi,
            "last_move_number": self.bridge.last_move_number,
            "live_winrate": self.bridge.live_winrate,
        }

    def _api_board(self):
        stones = []
        for n, (color, vertex) in self.bridge.fox_moves.items():
            v = self.bridge._gtp_to_xy(vertex)
            if v:
                stones.append({
                    "move_number": n,
                    "color": color,
                    "vertex": vertex,
                    "x": v[0],
                    "y": v[1],
                })
        return {
            "board_size": self.bridge.board_size,
            "komi": self.bridge.komi,
            "stones": stones,
        }

    def _api_candidates(self):
        cands = []
        for c in self.bridge._candidates.values():
            cands.append({
                "vertex": c.get("vertex"),
                "x": c.get("move", (0, 0))[0],
                "y": c.get("move", (0, 0))[1],
                "visits": c.get("visits", 0),
                "winrate": c.get("winrate", 0.0),
                "score": c.get("score", 0.0),
                "order": c.get("order", 999),
            })
        cands.sort(key=lambda c: c["order"])
        return {"candidates": cands}

    def _api_winrate(self):
        return {
            "data": [
                {"move": m, "black_winrate": wr}
                for m, wr in self.winrate_view.data
            ],
            "stdev": self.winrate_view.stdev,
        }

    def _api_score(self):
        return {
            "data": [
                {"move": m, "own_score_lead": s}
                for m, s in self.winrate_view.score_data
            ],
        }

    def _api_engine_info(self):
        return {
            "running": self.engine.is_running(),
            "remote_mode": getattr(self.engine, "_remote_mode", False),
            "ssh_mode": getattr(self.engine, "_ssh_mode", False),
            "path": self.engine_combo.currentText(),
            "weight": self.weight_combo.currentText(),
            "config": self.config_combo.currentText(),
            "comm_cmd": self.comm_cmd_edit.text(),
            "ssh_host": self.ssh_host_edit.text(),
        }

    def _api_send_gtp(self, cmd):
        if not self.engine.is_running():
            return False
        self.engine.send(cmd)
        self._log_gtp(f"[API] >>> {cmd}")
        return True

    def _api_start_engine(self):
        self._start_engine()
        return self.engine.is_running(), "已尝试启动引擎"

    def _api_stop_engine(self):
        self._stop_engine()
        return True, "引擎已停止"

    def _api_start_fox(self):
        self._start_fox()
        return True, "已尝试开始监听"

    def _api_stop_fox(self):
        self._stop_fox()
        return True, "野狐监听已停止"

    def _api_set_rules(self, rule):
        self.bridge.set_rules(rule)

    # ---------- 日志 ----------
    def _log_comm(self, msg):
        self.comm_signal.emit(msg)

    def _log_gtp(self, msg):
        self.gtp_signal.emit(msg)

    def _append_comm(self, msg):
        self.comm_text.append(msg)

    def _append_gtp(self, msg):
        self.gtp_text.append(msg)

    def _clear_comm(self):
        self.comm_text.clear()

    def _clear_gtp(self):
        self.gtp_text.clear()

    def _show_env_help(self):
        QMessageBox.information(
            self, "依赖环境",
            "SakuraGTP 1.4.1 依赖环境\n\n"
            "Windows 10 / 11，64 位\n"
            "VC++ 2010 x86 / VC++ 2015-2022 x64\n"
            "AI 引擎 (KataGo / LeelaZero)\n"
            "野狐围棋客户端 (AI 权限账号)\n"
            "paramiko (内嵌 SSH)"
        )

    def _show_usage_help(self):
        QMessageBox.information(
            self, "使用说明",
            "1. 选择本地引擎或 SSH 连接\n"
            "2. 启动引擎 / SSH 启动\n"
            "3. 开始监听\n"
            "4. 野狐客户端连接 127.0.0.1:6000\n"
            "5. 接受对局，AI 自动落子\n\n"
            "工具菜单：\n"
            "  HTTP API：启动本地 API\n"
            "  心跳设置：检测引擎假死\n"
            "  断线重连设置：野狐断开后自动等待重连\n"
            "  API Token 设置：保护 API 不被乱调"
        )

    def _show_about(self):
        QMessageBox.information(
            self, "关于",
            "SakuraGTP 1.4.1\n野狐围棋 AI 连线器"
        )

    def closeEvent(self, event):
        if self.engine.is_running():
            ret = QMessageBox.question(
                self, "引擎未关闭",
                "引擎进程仍在运行，是否停止并关闭？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if ret == QMessageBox.Yes:
                # 先停跑谱
                if hasattr(self, "runner"):
                    self.runner.stop()
                self._stop_engine()
                try:
                    self.fox.stop()
                except Exception:
                    pass
                if self.api_server:
                    self.api_server.stop()
                self._collect_cfg()
                save_config(self.cfg)
                event.accept()
            else:
                event.ignore()
            return

        # 引擎没运行，正常关闭
        if hasattr(self, "runner"):
            self.runner.stop()
        self._collect_cfg()
        save_config(self.cfg)
        try:
            self.fox.stop()
        except Exception:
            pass
        if self.api_server:
            self.api_server.stop()
        event.accept()
