import os
import re
import socket
import threading
import time
import math

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QFileDialog, QMessageBox,
    QTextEdit, QFormLayout,
    QDialog, QScrollArea, QStackedWidget, QAction, QActionGroup,
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QEvent
from PyQt5.QtGui import QColor, QPalette, QPainter

from config import load_config, save_config, push_history
from engine_manager import EngineManager
from fox_client import FoxClientServer
from gtp_bridge import GTPBridge
from board_view import BoardView
from winrate_view import WinrateView
from api_server import APIServer
from runner import ContributeRunner
import theme
from theme import build_app_stylesheet, placeholder_color, is_dark, set_active_palette, sci_fi_bg
from sci_widgets import (
    GlowButton, GlowLineEdit, GlowComboBox, GlowCheckBox,
    HudGroupBox, SciFiTabWidget,
)
from starfield import Starfield, DAY_CYCLE_SEC
from starcursor import make_star_cursor, StarTrailWidget
import ui_dialogs


class SakuraGTPApp(QMainWindow):
    comm_signal = pyqtSignal(str)
    gtp_signal = pyqtSignal(str)
    candidate_signal = pyqtSignal(list)
    board_signal = pyqtSignal()
    engine_exit_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("SakuraGTP 1.5.0 - 野狐围棋 AI 连线器")
        self.resize(1800, 1000)
        self.setMinimumSize(1480, 860)

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

        # 深空星图背景
        self._starfield = Starfield()
        self._bg_mode = self.cfg.get("bg_mode", "starfield")
        if self._bg_mode not in ("starfield", "daynight"):
            self._bg_mode = "starfield"
        self._dark_ui = True
        self._twinkle_timer = QTimer(self)
        self._twinkle_timer.setInterval(80)
        self._twinkle_timer.timeout.connect(self.update)

        self._idle_thread = threading.Thread(target=self._idle_loop, daemon=True)
        self._idle_thread.start()

        self._build_ui()
        self._connect_signals()
        self._apply_engine_params()

        # 四芒星光标 + 流星尾迹
        self.setCursor(make_star_cursor())
        self._trail = StarTrailWidget(self)
        self._trail.resize(self.size())
        self._trail.raise_()
        QApplication.instance().installEventFilter(self)

        # 统一科幻暗色主题（星空）；棋盘与胜率曲线默认同为星空暗色
        self._apply_bg_color(sci_fi_bg())

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

        self._build_status_bar()

    # ============================================================ 星图背景
    def eventFilter(self, obj, event):
        """全局鼠标移动 -> 主界面范围内的流星尾迹。"""
        if event.type() == QEvent.MouseMove and getattr(self, "_trail", None):
            try:
                w = QApplication.widgetAt(event.globalPos())
                if w is not None and (w is self or self.isAncestorOf(w)):
                    self._trail.add_point(self._trail.mapFromGlobal(event.globalPos()))
            except Exception:
                pass
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        trail = getattr(self, "_trail", None)
        if trail is not None:
            trail.resize(self.size())
            trail.raise_()

    def paintEvent(self, event):
        p = QPainter(self)
        day = 0.0
        if self._bg_mode == "daynight":
            phase = (time.time() % DAY_CYCLE_SEC) / DAY_CYCLE_SEC
            day = 0.5 - 0.5 * math.cos(2.0 * math.pi * phase)
        self._starfield.paint(p, self.width(), self.height(), time.time(), day)
        p.end()

    def _set_bg_mode(self, mode):
        if self._bg_mode == mode:
            return
        self._bg_mode = mode
        self.cfg["bg_mode"] = mode
        save_config(self.cfg)
        self.update()

    # ============================================================ 状态栏
    def _build_status_bar(self):
        bar = self.statusBar()
        self._sb_engine = QLabel()
        self._sb_fox = QLabel()
        self._sb_game = QLabel()
        for w in (self._sb_engine, self._sb_fox, self._sb_game):
            bar.addPermanentWidget(w)
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(800)
        self._status_timer.timeout.connect(self._update_status_bar)
        self._status_timer.start()
        self._update_status_bar()

    def _update_status_bar(self):
        pal = theme.pal()
        if self.engine.is_running():
            self._sb_engine.setText(
                f"<span style='color:{pal['ok'].name()}'>●</span> 引擎运行中")
        else:
            self._sb_engine.setText(
                f"<span style='color:{pal['danger'].name()}'>●</span> 引擎已停止")
        if self.fox.is_connected():
            self._sb_fox.setText(
                f"<span style='color:{pal['accent'].name()}'>●</span> 野狐已连接")
        elif self.fox.is_listening():
            self._sb_fox.setText(
                f"<span style='color:#FFD54F'>●</span> 野狐监听中")
        else:
            self._sb_fox.setText(
                f"<span style='color:{pal['dim'].name()}'>●</span> 野狐未监听")
        n = max(0, self.bridge.last_move_number)
        self._sb_game.setText(f"手数 {n} · AI {self.bridge.ai_color}")

    # ============================================================ UI 构建
    def _build_ui(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("文件")
        file_menu.addAction("保存配置", self._save_cfg)
        file_menu.addAction("退出", self.close)

        view_menu = menubar.addMenu("个性化")
        self.act_starfield = QAction("星空背景", self, checkable=True)
        self.act_daynight = QAction("昼夜更替（3 分钟循环）", self, checkable=True)
        bg_group = QActionGroup(self)
        bg_group.setExclusive(True)
        bg_group.addAction(self.act_starfield)
        bg_group.addAction(self.act_daynight)
        view_menu.addAction(self.act_starfield)
        view_menu.addAction(self.act_daynight)
        self.act_starfield.setChecked(self._bg_mode == "starfield")
        self.act_daynight.setChecked(self._bg_mode == "daynight")
        self.act_starfield.toggled.connect(
            lambda on: on and self._set_bg_mode("starfield"))
        self.act_daynight.toggled.connect(
            lambda on: on and self._set_bg_mode("daynight"))

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
        left_scroll.setMinimumWidth(880)
        left_scroll.setMaximumWidth(1040)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        left_scroll.setFrameShape(QScrollArea.NoFrame)
        left_scroll.viewport().setObjectName("sfViewport")
        left_scroll.viewport().setAttribute(Qt.WA_OpaquePaintEvent, False)
        left_scroll.viewport().setAutoFillBackground(False)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        self._build_left(left_layout)
        left_scroll.setWidget(left)
        # setWidget 会把 autoFill 重新打开，必须在之后关闭（透出星图）
        left.setAutoFillBackground(False)

        self.left_scroll = left_scroll
        self._build_right(main_layout, left_scroll)

    def _build_left(self, layout):
        mode_group = HudGroupBox("引擎模式")
        mode_layout = QHBoxLayout()
        self.btn_mode_local = GlowButton("本地引擎")
        self.btn_mode_local.clicked.connect(lambda: self._switch_mode("local"))
        self.btn_mode_ssh = GlowButton("SSH 连接")
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

        engine_group = HudGroupBox("本地引擎设置")
        engine_form = QFormLayout()
        engine_form.setVerticalSpacing(10)
        engine_form.setHorizontalSpacing(8)
        engine_form.setContentsMargins(8, 8, 8, 8)

        self.engine_combo = GlowComboBox()
        self.engine_combo.setEditable(True)
        self.engine_combo.addItems(self.cfg.get("engine_history", []))
        self.engine_combo.setCurrentText(self.cfg.get("engine_path", ""))
        self.engine_combo.setMinimumHeight(34)
        self.btn_browse_engine = GlowButton("浏览")
        self.btn_browse_engine.clicked.connect(self._browse_engine)
        row = QHBoxLayout()
        row.addWidget(self.engine_combo)
        row.addWidget(self.btn_browse_engine)
        engine_form.addRow("引擎:", row)

        self.weight_combo = GlowComboBox()
        self.weight_combo.setEditable(True)
        self.weight_combo.addItems(self.cfg.get("weight_history", []))
        self.weight_combo.setCurrentText(self.cfg.get("weight_path", ""))
        self.weight_combo.setMinimumHeight(34)
        self.btn_browse_weight = GlowButton("浏览")
        self.btn_browse_weight.clicked.connect(self._browse_weight)
        row = QHBoxLayout()
        row.addWidget(self.weight_combo)
        row.addWidget(self.btn_browse_weight)
        engine_form.addRow("权重:", row)

        self.config_combo = GlowComboBox()
        self.config_combo.setEditable(True)
        self.config_combo.addItems(self.cfg.get("config_history", []))
        self.config_combo.setCurrentText(self.cfg.get("config_path", ""))
        self.config_combo.setMinimumHeight(34)
        self.btn_browse_config = GlowButton("浏览")
        self.btn_browse_config.clicked.connect(self._browse_config)
        row = QHBoxLayout()
        row.addWidget(self.config_combo)
        row.addWidget(self.btn_browse_config)
        engine_form.addRow("配置:", row)

        comm_row = QHBoxLayout()
        self.comm_cmd_edit = GlowLineEdit(self.cfg.get("comm_cmd", ""))
        self.comm_cmd_edit.setPlaceholderText(
            '通用命令行（本地或 plink/ikatago），例如: plink -ssh ...'
        )
        comm_row.addWidget(self.comm_cmd_edit, stretch=1)

        btn_auto_cmd = GlowButton("自动生成")
        btn_auto_cmd.clicked.connect(self._auto_gen_cmd)
        comm_row.addWidget(btn_auto_cmd)
        engine_form.addRow("通用命令行:", comm_row)

        engine_group.setLayout(engine_form)
        local_layout.addWidget(engine_group)

        local_btn_layout = QHBoxLayout()
        self.btn_start_engine = GlowButton("启动引擎")
        self.btn_start_engine.clicked.connect(self._start_engine)
        self.btn_stop_engine = GlowButton("停止引擎")
        self.btn_stop_engine.clicked.connect(self._stop_engine)
        self.btn_stop_engine.setEnabled(False)
        local_btn_layout.addWidget(self.btn_start_engine)
        local_btn_layout.addWidget(self.btn_stop_engine)
        local_layout.addLayout(local_btn_layout)

        local_fox_group = HudGroupBox("野狐客户端监听")
        local_fox_layout = QHBoxLayout()
        local_fox_layout.addWidget(QLabel("端口:"))
        self.fox_port_edit = GlowLineEdit(str(self.cfg.get("fox_listen_port", 6000)))
        self.fox_port_edit.setFixedWidth(80)
        local_fox_layout.addWidget(self.fox_port_edit)
        self.btn_start_fox_local = GlowButton("开始监听")
        self.btn_start_fox_local.clicked.connect(self._start_fox)
        self.btn_stop_fox_local = GlowButton("停止监听")
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

        ssh_group = HudGroupBox("SSH 连接设置")
        ssh_form = QFormLayout()
        ssh_form.setVerticalSpacing(10)
        ssh_form.setHorizontalSpacing(8)
        ssh_form.setContentsMargins(8, 8, 8, 8)

        self.ssh_host_edit = GlowLineEdit("")
        self.ssh_host_edit.setPlaceholderText("远程 IP 或域名")
        ssh_form.addRow("主机:", self.ssh_host_edit)

        self.ssh_port_edit = GlowLineEdit("22")
        self.ssh_port_edit.setFixedWidth(80)
        ssh_form.addRow("端口:", self.ssh_port_edit)

        self.ssh_user_edit = GlowLineEdit("")
        self.ssh_user_edit.setPlaceholderText("用户名")
        ssh_form.addRow("用户名:", self.ssh_user_edit)

        self.ssh_pass_edit = GlowLineEdit("")
        self.ssh_pass_edit.setEchoMode(QLineEdit.Password)
        self.ssh_pass_edit.setPlaceholderText("密码（可选）")
        ssh_form.addRow("密码:", self.ssh_pass_edit)

        key_row = QHBoxLayout()
        self.ssh_key_edit = GlowLineEdit("")
        self.ssh_key_edit.setPlaceholderText("私钥路径（可选）")
        key_row.addWidget(self.ssh_key_edit, stretch=1)
        btn_browse_key = GlowButton("浏览")
        btn_browse_key.clicked.connect(self._browse_ssh_key)
        key_row.addWidget(btn_browse_key)
        ssh_form.addRow("私钥:", key_row)

        self.ssh_cmd_edit = GlowLineEdit("")
        self.ssh_cmd_edit.setPlaceholderText(
            '例: cd /root && ./katago gtp -model model.bin.gz -config gtp.cfg'
        )
        ssh_form.addRow("命令:", self.ssh_cmd_edit)

        ssh_group.setLayout(ssh_form)
        ssh_layout.addWidget(ssh_group)

        ssh_btn_layout = QHBoxLayout()
        self.btn_start_ssh = GlowButton("SSH 启动")
        self.btn_start_ssh.clicked.connect(self._start_ssh)
        self.btn_stop_ssh = GlowButton("SSH 停止")
        self.btn_stop_ssh.clicked.connect(self._stop_engine)
        self.btn_stop_ssh.setEnabled(False)
        ssh_btn_layout.addWidget(self.btn_start_ssh)
        ssh_btn_layout.addWidget(self.btn_stop_ssh)
        ssh_layout.addLayout(ssh_btn_layout)

        ssh_fox_group = HudGroupBox("野狐客户端监听")
        ssh_fox_layout = QHBoxLayout()
        ssh_fox_layout.addWidget(QLabel("端口:"))
        self.ssh_fox_port_edit = GlowLineEdit(str(self.cfg.get("fox_listen_port", 6000)))
        self.ssh_fox_port_edit.setFixedWidth(80)
        ssh_fox_layout.addWidget(self.ssh_fox_port_edit)
        self.btn_start_fox_ssh = GlowButton("开始监听")
        self.btn_start_fox_ssh.clicked.connect(self._start_fox_ssh)
        self.btn_stop_fox_ssh = GlowButton("停止监听")
        self.btn_stop_fox_ssh.clicked.connect(self._stop_fox)
        self.btn_stop_fox_ssh.setEnabled(False)
        ssh_fox_layout.addWidget(self.btn_start_fox_ssh)
        ssh_fox_layout.addWidget(self.btn_stop_fox_ssh)
        ssh_fox_group.setLayout(ssh_fox_layout)
        ssh_layout.addWidget(ssh_fox_group)

        ssh_layout.addStretch()
        self.mode_stack.addWidget(ssh_page)

        layout.addWidget(self.mode_stack)

        # 落子参数（已合并到 genmove_analyze，始终可见）
        live_group = HudGroupBox("落子参数（genmove_analyze）")
        live_layout = QVBoxLayout()

        self.winrate_param_widget = QWidget()
        param_layout = QFormLayout(self.winrate_param_widget)
        param_layout.setVerticalSpacing(10)
        param_layout.setContentsMargins(0, 0, 0, 0)

        self.max_time_edit = GlowLineEdit(str(self.cfg.get("max_time", 5)))
        param_layout.addRow("maxTime:", self.max_time_edit)

        self.max_visits_edit = GlowLineEdit(str(self.cfg.get("max_visits", 0)))
        param_layout.addRow("maxVisits:", self.max_visits_edit)

        self.max_playouts_edit = GlowLineEdit(str(self.cfg.get("max_playouts", 0)))
        param_layout.addRow("maxPlayouts:", self.max_playouts_edit)

        self.btn_refresh_state = GlowButton("刷新落子参数")
        self.btn_refresh_state.clicked.connect(self._refresh_state)
        param_layout.addRow("", self.btn_refresh_state)

        self.winrate_param_widget.setVisible(True)
        live_layout.addWidget(self.winrate_param_widget)

        live_group.setLayout(live_layout)
        layout.addWidget(live_group)

        # 规则快速切换
        rules_group = HudGroupBox("规则快速切换")
        rules_layout = QHBoxLayout()
        self.btn_chinese_rules = GlowButton("中国规则")
        self.btn_chinese_rules.clicked.connect(lambda: self._send_rule("chinese"))
        self.btn_japanese_rules = GlowButton("日本规则")
        self.btn_japanese_rules.clicked.connect(lambda: self._send_rule("japanese"))
        rules_layout.addWidget(self.btn_chinese_rules)
        rules_layout.addWidget(self.btn_japanese_rules)
        rules_group.setLayout(rules_layout)
        layout.addWidget(rules_group)

        # GTP Shell
        shell_group = HudGroupBox("GTP Shell")
        shell_layout = QVBoxLayout()

        snippet_row = QHBoxLayout()
        snippet_row.addWidget(QLabel("常用指令:"))
        self.snippet_combo = GlowComboBox()
        self.snippet_combo.addItem("（无）")
        for s in self.cfg.get("gtp_snippets", []):
            self.snippet_combo.addItem(s)
        self.snippet_combo.currentTextChanged.connect(self._on_snippet_selected)
        snippet_row.addWidget(self.snippet_combo, stretch=1)
        btn_manage_snippets = GlowButton("管理")
        btn_manage_snippets.clicked.connect(self._manage_snippets)
        snippet_row.addWidget(btn_manage_snippets)
        shell_layout.addLayout(snippet_row)

        self.shell_edit = GlowLineEdit()
        self.shell_edit.returnPressed.connect(self._send_shell)
        shell_layout.addWidget(self.shell_edit)

        btn_send_shell = GlowButton("发送 GTP 命令")
        btn_send_shell.clicked.connect(self._send_shell)
        shell_layout.addWidget(btn_send_shell)

        shell_group.setLayout(shell_layout)
        layout.addWidget(shell_group)

        # 跑谱状态
        self.contribute_group = HudGroupBox("跑谱状态")
        contrib_layout = QHBoxLayout()
        self.contribute_label = QLabel("未运行")
        contrib_layout.addWidget(self.contribute_label)
        self.btn_stop_contribute = GlowButton("停止跑谱")
        self.btn_stop_contribute.setEnabled(False)
        self.btn_stop_contribute.clicked.connect(self._manual_stop_contribute)
        contrib_layout.addWidget(self.btn_stop_contribute)
        contrib_layout.addStretch()
        self.contribute_group.setLayout(contrib_layout)
        layout.addWidget(self.contribute_group)

        layout.addStretch()

    def _build_right(self, main_layout, left_scroll):
        self.tabs = SciFiTabWidget()

        comm_tab = QWidget()
        comm_layout = QVBoxLayout(comm_tab)
        comm_layout.setContentsMargins(2, 2, 2, 2)
        comm_layout.setSpacing(2)

        comm_ctrl = QHBoxLayout()
        comm_ctrl.addStretch()
        btn_clear_comm = GlowButton("清空")
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
        btn_clear_gtp = GlowButton("清空")
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
        self.show_cand_check = GlowCheckBox("显示选点")
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
        btn_clear_wr = GlowButton("清空曲线")
        btn_clear_wr.clicked.connect(self._clear_winrate_curve)
        wr_ctrl.addWidget(btn_clear_wr)

        btn_export_wr = GlowButton("导出图片")
        btn_export_wr.clicked.connect(self._export_winrate_image)
        wr_ctrl.addWidget(btn_export_wr)

        btn_detach_wr = GlowButton("独立窗口")
        btn_detach_wr.clicked.connect(self._detach_winrate)
        wr_ctrl.addWidget(btn_detach_wr)

        wr_ctrl.addStretch()
        winrate_layout.addLayout(wr_ctrl)

        self.winrate_view = WinrateView()
        winrate_layout.addWidget(self.winrate_view, stretch=1)

        self.tabs.addTab(winrate_tab, "胜率曲线")

        main_layout.addWidget(left_scroll, stretch=1)
        main_layout.addWidget(self.tabs, stretch=2)

    def _connect_signals(self):
        self.comm_signal.connect(self._append_comm)
        self.gtp_signal.connect(self._append_gtp)
        self.candidate_signal.connect(self._on_candidate)
        self.board_signal.connect(self._do_update_board)
        self.engine_exit_signal.connect(self._stop_engine)

    # ============================================================ 模式切换 / 浏览
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

    # ============================================================ 引擎控制
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

        # 确定实际使用的 gtp.cfg 路径：优先命令行里的 -config，其次 UI 里的 config_path
        effective_config = ""
        if comm_cmd:
            effective_config = self._extract_config_from_cmd(comm_cmd)
        if not effective_config:
            effective_config = config_path

        if effective_config:
            cfg_vals = self._load_gtp_cfg(effective_config)
            # 无条件覆盖：未出现或被注释 -> 0；未注释 -> 配置文件里的值
            self.max_time_edit.setText(cfg_vals["max_time"])
            self.max_visits_edit.setText(cfg_vals["max_visits"])
            self.max_playouts_edit.setText(cfg_vals["max_playouts"])
            self._log_comm(f"从配置文件读取落子参数: {effective_config}")

        self._apply_engine_params()

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
        if self.engine.is_running():
            self._log_comm("发送 GTP: quit")
        self.engine.stop()
        self._log_comm("引擎已停止")
        self.btn_start_engine.setEnabled(True)
        self.btn_stop_engine.setEnabled(False)
        self.btn_start_ssh.setEnabled(True)
        self.btn_stop_ssh.setEnabled(False)

        if self.fox.is_connected():
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

    # ============================================================ 自动跑谱
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

    # ============================================================ 野狐监听
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

    # ============================================================ 规则 / 对局事件
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

    # ============================================================ 引擎输出 / 胜率
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

    def _apply_engine_params(self):
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
        self._apply_engine_params()
        self._log_comm("参数已刷新")

    # ============================================================ 棋盘
    def _do_update_board(self):
        board = {}
        played = []
        # 让子手数为负数，sorted 后排在最前，先画让子再画正式手数
        for n in sorted(self.bridge.fox_moves.keys()):
            color, vertex = self.bridge.fox_moves[n]
            v = self.bridge._gtp_to_xy(vertex)
            if not v:
                continue
            x, y = v
            if (x, y) in board:
                continue
            board[(x, y)] = color
            played.append((n, color, x, y))
            self._remove_captured(board, x, y, color)

        stones = {}
        for n, color, x, y in played:
            if board.get((x, y)) == color:
                stones[n] = (color, x, y)
        self.board_view.set_stones(stones)
        if played:
            self.board_view.set_last_move((played[-1][1], played[-1][2], played[-1][3]))

    def _remove_captured(self, board, x, y, color):
        size = self.bridge.board_size
        opponent = "W" if color == "B" else "B"
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if not (0 <= nx < size and 0 <= ny < size):
                continue
            if (nx, ny) not in board or board[(nx, ny)] != opponent:
                continue
            group = self._collect_group(board, nx, ny)
            if not self._has_liberty(board, group):
                for gx, gy in group:
                    board.pop((gx, gy), None)

    def _collect_group(self, board, x, y):
        size = self.bridge.board_size
        color = board[(x, y)]
        stack = [(x, y)]
        seen = set()
        while stack:
            cx, cy = stack.pop()
            if (cx, cy) in seen:
                continue
            seen.add((cx, cy))
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = cx + dx, cy + dy
                if not (0 <= nx < size and 0 <= ny < size):
                    continue
                if (nx, ny) in board and board[(nx, ny)] == color and (nx, ny) not in seen:
                    stack.append((nx, ny))
        return seen

    def _has_liberty(self, board, group):
        size = self.bridge.board_size
        for gx, gy in group:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = gx + dx, gy + dy
                if not (0 <= nx < size and 0 <= ny < size):
                    continue
                if (nx, ny) not in board:
                    return True
        return False

    def _on_show_cand_change(self, state):
        self.board_view.set_show_candidates(bool(state))

    # ============================================================ 胜率曲线
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

        chk_top = GlowCheckBox("总在最前")
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

    # ============================================================ GTP Shell
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
        ui_dialogs.manage_snippets(self)

    # ============================================================ 主题
    def _apply_bg_color(self, color_hex):
        try:
            c = QColor(color_hex)
            if not c.isValid():
                return
        except Exception:
            return

        self.setStyleSheet(build_app_stylesheet(color_hex))
        set_active_palette(color_hex)

        palette = self.palette()
        palette.setColor(QPalette.PlaceholderText, QColor(placeholder_color(color_hex)))
        self.setPalette(palette)

        # 深色 -> 星图闪烁；浅色 -> 柔和渐变
        self._dark_ui = is_dark(color_hex)
        if self._dark_ui:
            self._twinkle_timer.start()
        else:
            self._twinkle_timer.stop()
        self.update()

        self.cfg["bg_color"] = color_hex
        save_config(self.cfg)

    # ============================================================ 工具菜单对话框
    def _open_heartbeat_dialog(self):
        ui_dialogs.open_heartbeat_dialog(self)

    def _open_reconnect_dialog(self):
        ui_dialogs.open_reconnect_dialog(self)

    def _open_token_dialog(self):
        ui_dialogs.open_token_dialog(self)

    # ============================================================ HTTP API
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
        api_port_edit = GlowLineEdit(str(self.cfg.get("api_port", 8765)))
        api_port_edit.setFixedWidth(80)
        ctrl.addWidget(api_port_edit)

        btn_start = GlowButton("启动 API")
        btn_stop = GlowButton("停止 API")
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
        ui_dialogs.open_contribute_dialog(self)

    def _on_api_window_closed(self):
        self.api_window = None

    # ============================================================ 配置
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
        """
        从 gtp.cfg 读取 maxTime / maxVisits / maxPlayouts。
        返回 dict，包含 max_time / max_visits / max_playouts 三个 key：
        - 参数未出现或出现但被 # 注释：值设为 0
        - 参数存在且未注释：值为配置文件里的数值（字符串）
        """
        result = {
            "max_time": "0",
            "max_visits": "0",
            "max_playouts": "0",
        }
        found = {
            "max_time": False,
            "max_visits": False,
            "max_playouts": False,
        }
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                for line in f:
                    raw = line.strip()
                    if not raw:
                        continue
                    commented = raw.startswith("#")
                    if commented:
                        s = raw.lstrip("#").strip()
                    else:
                        s = raw
                    if "=" not in s:
                        continue
                    key, val = s.split("=", 1)
                    key = key.strip()
                    val = val.strip()
                    if key == "maxTime":
                        found["max_time"] = True
                        result["max_time"] = "0" if commented else val
                    elif key == "maxVisits":
                        found["max_visits"] = True
                        result["max_visits"] = "0" if commented else val
                    elif key == "maxPlayouts":
                        found["max_playouts"] = True
                        result["max_playouts"] = "0" if commented else val
        except Exception:
            pass
        return result

    def _extract_config_from_cmd(self, cmd):
        """
        从命令行里解析 -config / --config 后面的路径。
        支持带引号和不带引号。
        """
        if not cmd:
            return ""
        # 匹配 -config "xxx" / -config xxx / --config "xxx" / --config xxx
        m = re.search(r'(?:^|\s)--?config\s+("([^"]+)"|(\S+))', cmd)
        if not m:
            return ""
        if m.group(2):
            return m.group(2)
        return m.group(3) or ""

    # ============================================================ API 回调
    def _api_status(self):
        return {
            "engine_running": self.engine.is_running(),
            "fox_listening": self.fox.is_connected(),
            "api_running": self.api_server.is_running() if self.api_server else False,
            "ai_color": self.bridge.ai_color,
            "board_size": self.bridge.board_size,
            "komi": self.bridge.komi,
            "last_move_number": self.bridge.last_move_number,
            "mode": "genmove_analyze",
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

    # ============================================================ 日志
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

    # ============================================================ 帮助
    def _show_env_help(self):
        QMessageBox.information(
            self, "依赖环境",
            "SakuraGTP 1.5.0 依赖环境\n\n"
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
            "落子与分析已合并为 kata-genmove_analyze：\n"
            "  AI 落子的同时实时显示选点、胜率、目差、计算量。\n\n"
            "工具菜单：\n"
            "  HTTP API：启动本地 API\n"
            "  心跳设置：检测引擎假死\n"
            "  断线重连设置：野狐断开后自动等待重连\n"
            "  API Token 设置：保护 API 不被乱调"
        )

    def _show_about(self):
        QMessageBox.information(
            self, "关于",
            "SakuraGTP 1.5.0\n野狐围棋 AI 连线器"
        )

    # ============================================================ 关闭
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
