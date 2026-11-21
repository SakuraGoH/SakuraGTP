"""Dialogs: settings, GTP shell, board windows, help/about."""

import os
import threading

from PyQt5.QtCore import QObject, Qt, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                             QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
                             QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                             QPlainTextEdit, QPushButton, QSpinBox, QTabWidget,
                             QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from foxgtp.config import build_engine_command, save_config

from . import theme
from .board_widget import BoardWidget
from .winrate_widget import WinrateWidget


def _hline():
    layout = QHBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    return layout


class SettingsDialog(QDialog):
    def __init__(self, parent, config, tr, on_apply=None):
        super().__init__(parent)
        self.config = config
        self.tr = tr
        self.on_apply = on_apply
        self.setWindowTitle(tr("settings_title"))
        self.setMinimumWidth(640)
        self._build()
        self._load()

    # ------------------------------------------------------------------ build
    def _build(self):
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._tab_engine(), self.tr("tab_engine"))
        tabs.addTab(self._tab_fox(), self.tr("tab_fox"))
        tabs.addTab(self._tab_time(), self.tr("tab_time"))
        tabs.addTab(self._tab_search(), self.tr("tab_search"))
        tabs.addTab(self._tab_ui(), self.tr("tab_ui"))
        layout.addWidget(tabs)

        buttons = QDialogButtonBox()
        self.btn_ok = buttons.addButton(self.tr("btn_ok"), QDialogButtonBox.AcceptRole)
        self.btn_cancel = buttons.addButton(self.tr("btn_cancel"), QDialogButtonBox.RejectRole)
        self.btn_apply = buttons.addButton(self.tr("btn_apply"), QDialogButtonBox.ApplyRole)
        self.btn_apply.clicked.connect(self._apply_only)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _tab_engine(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()

        self.channel_combo = QComboBox()
        self.channel_combo.addItem(self.tr("channel_stdio"), "stdio")
        self.channel_combo.addItem(self.tr("channel_tcp_client"), "tcp-client")
        self.channel_combo.addItem(self.tr("channel_tcp_server"), "tcp-server")
        form.addRow(self.tr("label_channel"), self.channel_combo)

        self.path_edit = QLineEdit()
        browse = QPushButton(self.tr("btn_browse"))
        browse.clicked.connect(self._browse_engine)
        row = _hline()
        row.addWidget(self.path_edit, 1)
        row.addWidget(browse)
        form.addRow(self.tr("label_path"), row)

        self.args_edit = QLineEdit()
        self.args_edit.setPlaceholderText("gtp -model model.bin.gz -config gtp.cfg")
        form.addRow(self.tr("label_args"), self.args_edit)

        self.command_edit = QLineEdit()
        self.command_edit.setPlaceholderText('留空则自动拼成: "<引擎>" <参数>')
        form.addRow(self.tr("label_command"), self.command_edit)

        self.workdir_edit = QLineEdit()
        workdir_browse = QPushButton(self.tr("btn_browse"))
        workdir_browse.clicked.connect(self._browse_workdir)
        row2 = _hline()
        row2.addWidget(self.workdir_edit, 1)
        row2.addWidget(workdir_browse)
        form.addRow(self.tr("label_workdir"), row2)

        self.host_edit = QLineEdit()
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        row3 = _hline()
        row3.addWidget(QLabel("IP"))
        row3.addWidget(self.host_edit, 1)
        row3.addWidget(QLabel(self.tr("label_port")))
        row3.addWidget(self.port_spin)
        form.addRow(self.tr("label_host"), row3)

        layout.addLayout(form)

        box = QGroupBox()
        box.setTitle("心跳 / 自动恢复")
        inner = QVBoxLayout(box)
        self.heartbeat_check = QCheckBox(self.tr("opt_heartbeat"))
        inner.addWidget(self.heartbeat_check)
        row4 = _hline()
        row4.addWidget(QLabel("间隔(秒)"))
        self.heartbeat_spin = QSpinBox()
        self.heartbeat_spin.setRange(1, 3600)
        row4.addWidget(self.heartbeat_spin)
        row4.addWidget(QLabel("超时(秒)"))
        self.heartbeat_timeout_spin = QSpinBox()
        self.heartbeat_timeout_spin.setRange(1, 600)
        row4.addWidget(self.heartbeat_timeout_spin)
        row4.addStretch(1)
        inner.addLayout(row4)
        self.recover_check = QCheckBox(self.tr("opt_auto_recover"))
        inner.addWidget(self.recover_check)
        row5 = _hline()
        row5.addWidget(QLabel("重连间隔(秒)"))
        self.recover_spin = QSpinBox()
        self.recover_spin.setRange(1, 600)
        row5.addWidget(self.recover_spin)
        row5.addStretch(1)
        inner.addLayout(row5)
        layout.addWidget(box)
        layout.addStretch(1)
        return page

    def _tab_fox(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.fox_port_spin = QSpinBox()
        self.fox_port_spin.setRange(1, 65535)
        form.addRow("监听端口", self.fox_port_spin)
        self.fox_host_edit = QLineEdit()
        form.addRow("监听地址", self.fox_host_edit)
        layout.addLayout(form)
        layout.addStretch(1)
        return page

    def _tab_time(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.go_byoyomi_check = QCheckBox(self.tr("opt_go_byoyomi"))
        layout.addWidget(self.go_byoyomi_check)

        row = _hline()
        self.data_transfer_check = QCheckBox(self.tr("opt_data_transfer"))
        self.data_transfer_spin = QSpinBox()
        self.data_transfer_spin.setRange(0, 600)
        row.addWidget(self.data_transfer_check)
        row.addWidget(self.data_transfer_spin)
        row.addStretch(1)
        layout.addLayout(row)

        row2 = _hline()
        self.ai_cal_check = QCheckBox(self.tr("opt_ai_cal_time"))
        self.ai_cal_spin = QSpinBox()
        self.ai_cal_spin.setRange(1, 3600)
        row2.addWidget(self.ai_cal_check)
        row2.addWidget(self.ai_cal_spin)
        row2.addStretch(1)
        layout.addLayout(row2)

        note = QLabel(
            "读秒换算说明：\n"
            "• 未勾选「围棋常用读秒」时，按加拿大读秒发送，s=1；\n"
            "• 勾选后 s=读秒次数；\n"
            "• 「数据传输耗时」会从读秒时间里扣除，防止野狐侧超时；\n"
            "• 「AI 读秒时间」直接指定引擎读秒，与野狐读秒无关。")
        note.setWordWrap(True)
        note.setStyleSheet("color: %s;" % theme.MUTED)
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _tab_search(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        box = QGroupBox("KataGo 搜索限制（kata-set-param）")
        inner = QFormLayout(box)
        self.max_time_spin = QDoubleSpinBox()
        self.max_time_spin.setRange(0, 100000)
        self.max_time_spin.setDecimals(2)
        self.max_visits_spin = QSpinBox()
        self.max_visits_spin.setRange(0, 100000000)
        self.max_playouts_spin = QSpinBox()
        self.max_playouts_spin.setRange(0, 100000000)
        self.genmove_timeout_spin = QDoubleSpinBox()
        self.genmove_timeout_spin.setRange(0, 3600)
        self.genmove_timeout_spin.setDecimals(1)
        self.genmove_timeout_spin.setToolTip("0 = 自动")
        inner.addRow("maxTime (秒)", self.max_time_spin)
        inner.addRow("maxVisits", self.max_visits_spin)
        inner.addRow("maxPlayouts", self.max_playouts_spin)
        inner.addRow("落子看门狗 (秒)", self.genmove_timeout_spin)
        layout.addWidget(box)

        box2 = QGroupBox("分析与规则")
        inner2 = QFormLayout(box2)
        self.analyze_check = QCheckBox(self.tr("opt_analysis"))
        inner2.addRow(self.analyze_check)
        self.analyze_interval_spin = QSpinBox()
        self.analyze_interval_spin.setRange(10, 5000)
        inner2.addRow("分析间隔 (ms)", self.analyze_interval_spin)
        self.analyze_maxmoves_spin = QSpinBox()
        self.analyze_maxmoves_spin.setRange(1, 50)
        inner2.addRow("候选点数量", self.analyze_maxmoves_spin)
        self.rule_combo = QComboBox()
        for label, value in (("不设置", ""), ("中国规则", "chinese"),
                             ("日本规则", "japanese"), ("韩国规则", "korean"),
                             ("Tromp-Taylor", "tromp-taylor"), ("AGA", "aga"),
                             ("新西兰", "new-zealand")):
            self.rule_combo.addItem(label, value)
        inner2.addRow(self.tr("label_rule"), self.rule_combo)
        self.handicap_combo = QComboBox()
        for label, value in (("自动", "auto"), ("自由摆放", "free"),
                             ("固定让子", "fixed"), ("逐子落子", "play")):
            self.handicap_combo.addItem(label, value)
        inner2.addRow(self.tr("label_handicap_mode"), self.handicap_combo)
        layout.addWidget(box2)
        layout.addStretch(1)
        return page

    def _tab_ui(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.language_combo = QComboBox()
        self.language_combo.addItem("简体中文", "zh")
        self.language_combo.addItem("English", "en")
        form.addRow(self.tr("label_language"), self.language_combo)

        self.timestamp_check = QCheckBox(self.tr("opt_timestamp"))
        form.addRow(self.timestamp_check)
        self.save_log_check = QCheckBox(self.tr("opt_save_log"))
        form.addRow(self.save_log_check)
        self.log_dir_edit = QLineEdit()
        log_browse = QPushButton(self.tr("btn_browse"))
        log_browse.clicked.connect(self._browse_log_dir)
        row = _hline()
        row.addWidget(self.log_dir_edit, 1)
        row.addWidget(log_browse)
        form.addRow("日志目录", row)

        self.coordinates_check = QCheckBox(self.tr("opt_coordinates"))
        form.addRow(self.coordinates_check)
        self.move_numbers_check = QCheckBox(self.tr("opt_move_numbers"))
        form.addRow(self.move_numbers_check)
        self.candidates_check = QCheckBox("显示候选点")
        form.addRow(self.candidates_check)
        layout.addLayout(form)
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------ load/save
    def _load(self):
        cfg = self.config
        index = self.channel_combo.findData(cfg.get("channel", "stdio"))
        self.channel_combo.setCurrentIndex(max(0, index))
        self.path_edit.setText(cfg.get("engine_path", ""))
        self.args_edit.setText(cfg.get("engine_args", ""))
        self.command_edit.setText(cfg.get("engine_command", ""))
        self.workdir_edit.setText(cfg.get("working_dir", ""))
        self.host_edit.setText(cfg.get("engine_host", "127.0.0.1"))
        self.port_spin.setValue(int(cfg.get("engine_port") or 8000))
        self.fox_port_spin.setValue(int(cfg.get("fox_port") or 6000))
        self.fox_host_edit.setText(cfg.get("fox_host", "0.0.0.0"))

        self.heartbeat_check.setChecked(bool(cfg.get("heartbeat_enabled")))
        self.heartbeat_spin.setValue(int(cfg.get("heartbeat_interval") or 30))
        self.heartbeat_timeout_spin.setValue(int(cfg.get("heartbeat_timeout") or 10))
        self.recover_check.setChecked(bool(cfg.get("auto_recover", True)))
        self.recover_spin.setValue(int(cfg.get("recover_interval") or 5))

        self.go_byoyomi_check.setChecked(bool(cfg.get("use_go_byoyomi")))
        self.data_transfer_check.setChecked(bool(cfg.get("use_data_transfer_time")))
        self.data_transfer_spin.setValue(int(cfg.get("data_transfer_time") or 0))
        self.ai_cal_check.setChecked(bool(cfg.get("use_ai_cal_time")))
        self.ai_cal_spin.setValue(int(cfg.get("ai_cal_time") or 5))

        self.max_time_spin.setValue(float(cfg.get("max_time") or 0))
        self.max_visits_spin.setValue(int(cfg.get("max_visits") or 0))
        self.max_playouts_spin.setValue(int(cfg.get("max_playouts") or 0))
        self.genmove_timeout_spin.setValue(float(cfg.get("genmove_timeout") or 0))
        self.analyze_check.setChecked(bool(cfg.get("use_analyze", True)))
        self.analyze_interval_spin.setValue(int(cfg.get("analyze_interval_ms") or 50))
        self.analyze_maxmoves_spin.setValue(int(cfg.get("analyze_max_moves") or 12))
        self.rule_combo.setCurrentIndex(max(0, self.rule_combo.findData(cfg.get("rule", ""))))
        self.handicap_combo.setCurrentIndex(
            max(0, self.handicap_combo.findData(cfg.get("handicap_mode", "auto"))))

        self.language_combo.setCurrentIndex(
            max(0, self.language_combo.findData(cfg.get("language", "zh"))))
        self.timestamp_check.setChecked(bool(cfg.get("timestamp_in_log", True)))
        self.save_log_check.setChecked(bool(cfg.get("save_log", False)))
        self.log_dir_edit.setText(cfg.get("log_dir", "logs"))
        self.coordinates_check.setChecked(bool(cfg.get("show_coordinates", True)))
        self.move_numbers_check.setChecked(bool(cfg.get("show_move_numbers", False)))
        self.candidates_check.setChecked(bool(cfg.get("show_candidates", True)))

    def values(self):
        return {
            "channel": self.channel_combo.currentData(),
            "engine_path": self.path_edit.text().strip(),
            "engine_args": self.args_edit.text().strip(),
            "engine_command": self.command_edit.text().strip(),
            "working_dir": self.workdir_edit.text().strip(),
            "engine_host": self.host_edit.text().strip() or "127.0.0.1",
            "engine_port": int(self.port_spin.value()),
            "fox_port": int(self.fox_port_spin.value()),
            "fox_host": self.fox_host_edit.text().strip() or "0.0.0.0",
            "heartbeat_enabled": self.heartbeat_check.isChecked(),
            "heartbeat_interval": int(self.heartbeat_spin.value()),
            "heartbeat_timeout": int(self.heartbeat_timeout_spin.value()),
            "auto_recover": self.recover_check.isChecked(),
            "recover_interval": int(self.recover_spin.value()),
            "use_go_byoyomi": self.go_byoyomi_check.isChecked(),
            "use_data_transfer_time": self.data_transfer_check.isChecked(),
            "data_transfer_time": int(self.data_transfer_spin.value()),
            "use_ai_cal_time": self.ai_cal_check.isChecked(),
            "ai_cal_time": int(self.ai_cal_spin.value()),
            "max_time": float(self.max_time_spin.value()),
            "max_visits": int(self.max_visits_spin.value()),
            "max_playouts": int(self.max_playouts_spin.value()),
            "genmove_timeout": float(self.genmove_timeout_spin.value()),
            "use_analyze": self.analyze_check.isChecked(),
            "analyze_interval_ms": int(self.analyze_interval_spin.value()),
            "analyze_max_moves": int(self.analyze_maxmoves_spin.value()),
            "rule": self.rule_combo.currentData(),
            "handicap_mode": self.handicap_combo.currentData(),
            "language": self.language_combo.currentData(),
            "timestamp_in_log": self.timestamp_check.isChecked(),
            "save_log": self.save_log_check.isChecked(),
            "log_dir": self.log_dir_edit.text().strip() or "logs",
            "show_coordinates": self.coordinates_check.isChecked(),
            "show_move_numbers": self.move_numbers_check.isChecked(),
            "show_candidates": self.candidates_check.isChecked(),
        }

    def _apply_only(self):
        self.config.update(self.values())
        save_config(self.config)
        if self.on_apply:
            self.on_apply()

    def accept(self):
        self._apply_only()
        super().accept()

    # ------------------------------------------------------------------ browse
    def _browse_engine(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 AI 引擎", "",
                                              "可执行文件 (*.exe);;所有文件 (*.*)")
        if path:
            self.path_edit.setText(path)
            if not self.workdir_edit.text().strip():
                self.workdir_edit.setText(os.path.dirname(path))

    def _browse_workdir(self):
        path = QFileDialog.getExistingDirectory(self, "选择工作目录")
        if path:
            self.workdir_edit.setText(path)

    def _browse_log_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择日志目录")
        if path:
            self.log_dir_edit.setText(path)


class _ShellBridge(QObject):
    finished = pyqtSignal(str)


class ShellDialog(QDialog):
    def __init__(self, parent, controller, tr):
        super().__init__(parent)
        self.controller = controller
        self.tr = tr
        self.setWindowTitle(tr("shell_title"))
        self.resize(720, 460)

        layout = QVBoxLayout(self)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output, 1)

        row = _hline()
        self.input = QLineEdit()
        self.input.returnPressed.connect(self.send)
        self.btn_send = QPushButton(tr("btn_send"))
        self.btn_send.clicked.connect(self.send)
        row.addWidget(self.input, 1)
        row.addWidget(self.btn_send)
        layout.addLayout(row)

        quick = _hline()
        for command in ("list_commands", "version", "name", "protocol_version",
                        "final_score", "undo", "stop"):
            button = QPushButton(command)
            button.clicked.connect(lambda _checked=False, cmd=command: self.send_command(cmd))
            quick.addWidget(button)
        quick.addStretch(1)
        clear = QPushButton(tr("btn_clear"))
        clear.clicked.connect(self.output.clear)
        quick.addWidget(clear)
        layout.addLayout(quick)

        self._bridge = _ShellBridge()
        self._bridge.finished.connect(self._append)
        if not controller.transport:
            self._append("提示: 引擎尚未连接，命令会失败。")

    def send(self):
        command = self.input.text().strip()
        if not command:
            return
        self.input.clear()
        self.send_command(command)

    def send_command(self, command):
        self._append(">>> " + command)

        def worker():
            ok, text = self.controller.send_shell(command)
            self._bridge.finished.emit(("= " if ok else "? ") + (text or ""))

        threading.Thread(target=worker, daemon=True).start()

    def _append(self, text):
        self.output.appendPlainText(text)


class BoardWindow(QWidget):
    """Standalone board window (Fox board or AI engine board)."""

    clicked = pyqtSignal(int, int)
    right_clicked = pyqtSignal(int, int)

    def __init__(self, parent, title, tr, with_analysis=False, interactive=False):
        super().__init__(parent, Qt.Window)
        self.tr = tr
        self.setWindowTitle(title)
        self.resize(640, 760 if with_analysis else 660)
        self.with_analysis = with_analysis

        layout = QVBoxLayout(self)
        self.info = QLabel("—")
        self.info.setStyleSheet("color: %s; padding: 2px 4px;" % theme.MUTED)
        layout.addWidget(self.info)

        self.board = BoardWidget()
        self.board.interactive = interactive
        self.board.clicked.connect(self.clicked)
        self.board.right_clicked.connect(self.right_clicked)
        layout.addWidget(self.board, 1)

        if with_analysis:
            self.winrate = WinrateWidget()
            layout.addWidget(self.winrate)

            self.table = QTableWidget(0, 4)
            self.table.setHorizontalHeaderLabels(["手", "胜率", "目差", "访问"])
            self.table.verticalHeader().setVisible(False)
            self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            self.table.setMaximumHeight(150)
            layout.addWidget(self.table)

    def set_interactive(self, interactive):
        self.board.interactive = interactive

    def update_state(self, payload):
        self.board.set_state(
            board_size=payload.get("board_size", 19),
            moves=payload.get("moves", []),
            last_move=payload.get("last_move", 0),
            candidates=payload.get("candidates", []),
            ai_color=payload.get("ai_color", "B"),
            show_candidates=self.with_analysis,
        )
        winrate = payload.get("winrate")
        score = payload.get("score")
        text = "%s %s    %s %s" % (
            self.tr("label_move"), payload.get("last_move", 0),
            self.tr("label_winrate"),
            ("%.1f%%" % (winrate * 100)) if winrate is not None else "—")
        if score is not None:
            text += "    %s %+.1f" % (self.tr("label_score"), score)
        self.info.setText(text)

        if self.with_analysis:
            candidates = payload.get("candidates") or []
            self.table.setRowCount(len(candidates))
            for row, cand in enumerate(candidates[:20]):
                values = [cand.get("vertex", ""),
                          "%.1f%%" % (float(cand.get("winrate") or 0) * 100),
                          "%+.1f" % float(cand.get("score") or 0),
                          str(cand.get("visits", 0))]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setTextAlignment(Qt.AlignCenter)
                    self.table.setItem(row, column, item)

    def add_winrate_point(self, move_no, black_winrate, score=None):
        if self.with_analysis:
            self.winrate.add_point(move_no, black_winrate, score)

    def clear_all(self):
        self.board.clear()
        self.info.setText("—")
        if self.with_analysis:
            self.winrate.clear()
            self.table.setRowCount(0)


class HelpDialog(QDialog):
    def __init__(self, parent, title, html):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 560)
        layout = QVBoxLayout(self)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setPlainText(html)
        layout.addWidget(view)
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        layout.addWidget(close, 0, Qt.AlignRight)


HELP_TEXT = """FoxGTP-Py 使用说明
====================

1. 打开「设置」选择 AI 引擎通信方式：
   • 标准输入输出（STDIO）：填写引擎程序和参数，例如
       katago.exe gtp -model model.bin.gz -config gtp.cfg
   • TCP/IP: FoxGTP → AI 引擎：填写引擎的 IP 和端口（引擎作为服务端）
   • TCP/IP: AI 引擎 → FoxGTP：填写本地监听端口，让引擎主动连过来
2. 点击「连接 AI 引擎」，程序会自动探测引擎能力（协议版本、命令表），
   日志里会显示识别结果，例如：
       KataGo 1.13.0 [kata,kata-analyze,undo,final_score,...]
3. 在「设置 → 野狐客户端」里填写监听端口（默认 6000），点击「开始监听」。
4. 在野狐围棋客户端里填 127.0.0.1 和这个端口，点击「连接 AI」。
5. 对局开始后程序会自动同步棋谱、读秒、点目；断线或引擎重启会自动恢复。

提示
----
• AI 引擎棋盘窗口：显示引擎盘面、候选点和胜率曲线。
• 测试模式：在设置里勾选后，可直接在 AI 棋盘上左键落子、右键让引擎落子，
  不需要野狐客户端即可验证引擎是否正常。
• GTP Shell：可以发送任意 GTP 命令，包括引擎自己扩展的命令。
• 通信数据窗口会记录野狐协议和 GTP 双向数据，勾选「保存」会写入 logs 目录。
"""

ABOUT_TEXT = """FoxGTP-Py 1.0
================

野狐围棋 AI 连线器 —— 官方 FoxGTP 2.9 的 Python 复刻实现。

设计目标
--------
• 协议行为与 FoxGTP 保持一致（同样的核心 GTP 命令集、同样的棋谱差异同步、
  同样的读秒换算），因此兼容面同样广；
• 在此之上支持任意 GTP 命令与扩展命令（kata-*、lz-*、undo、stop 等），
  并在引擎不支持时自动退回核心命令；
• 支持不回显命令号的引擎、三种通信方式、心跳与自动恢复。

协议参考：野狐围棋AI接入协议 1.05 / 接入手册 2.01（北京野狐世纪）。
本程序与野狐官方无隶属关系。
"""
