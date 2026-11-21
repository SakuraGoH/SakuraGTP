"""Main window: connection panels, communication log, menus, child windows."""

import html
import os
import sys
import time

from PyQt5.QtCore import QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QAction, QCheckBox, QComboBox, QFileDialog, QGroupBox,
                             QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
                             QPlainTextEdit, QPushButton, QSpinBox, QSplitter,
                             QVBoxLayout, QWidget)

from foxgtp.config import build_engine_command, load_config, save_config
from foxgtp.controller import Controller
from foxgtp.logbook import ERROR, IN, INFO, OUT

from . import theme
from .i18n import Language
from .ui_dialogs import (ABOUT_TEXT, HELP_TEXT, BoardWindow, HelpDialog,
                         SettingsDialog, ShellDialog)

MAX_LOG_BLOCKS = 5000


class MainWindow(QMainWindow):
    event_signal = pyqtSignal(object, object)

    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.lang = Language(self.config.get("language", "zh"))
        self.controller = Controller(self.config, listener=self._listener)
        self.controller.apply_config(self.config)

        self.event_signal.connect(self._on_event, Qt.QueuedConnection)

        self.board_payload = {}
        self.ai_board_window = None
        self.fox_board_window = None
        self.shell_window = None
        self._widgets = {}

        self._build_ui()
        self._build_menus()
        self._retranslate()
        self._restore_geometry()

        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start(1000)
        self._refresh_status()

    # ================================================================== plumbing
    def _listener(self, topic, payload):
        """Called from controller threads: hop to the GUI thread."""
        self.event_signal.emit(topic, payload)

    def tr(self, key):
        return self.lang(key)

    # ================================================================== UI
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        splitter = QSplitter(Qt.Horizontal)

        # ---------------- left: connections ----------------
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 8, 8, 8)

        # Fox client group
        fox_group = QGroupBox()
        self._widgets["fox_group"] = fox_group
        fox_layout = QVBoxLayout(fox_group)
        row = QHBoxLayout()
        self.lbl_fox_port = QLabel()
        self._widgets["lbl_fox_port"] = self.lbl_fox_port
        self.fox_port_spin = QSpinBox()
        self.fox_port_spin.setRange(1, 65535)
        self.fox_port_spin.setValue(int(self.config.get("fox_port") or 6000))
        row.addWidget(self.lbl_fox_port)
        row.addWidget(self.fox_port_spin, 1)
        fox_layout.addLayout(row)

        row = QHBoxLayout()
        self.btn_start_fox = QPushButton()
        self.btn_start_fox.setObjectName("primary")
        self.btn_start_fox.clicked.connect(self._start_fox)
        self.btn_stop_fox = QPushButton()
        self.btn_stop_fox.clicked.connect(self._stop_fox)
        self.btn_stop_fox.setEnabled(False)
        row.addWidget(self.btn_start_fox)
        row.addWidget(self.btn_stop_fox)
        fox_layout.addLayout(row)

        self.lbl_fox_state = QLabel()
        self.lbl_fox_state.setWordWrap(True)
        fox_layout.addWidget(self.lbl_fox_state)
        left_layout.addWidget(fox_group)

        # Engine group
        engine_group = QGroupBox()
        self._widgets["engine_group"] = engine_group
        engine_layout = QVBoxLayout(engine_group)

        row = QHBoxLayout()
        self.lbl_channel = QLabel()
        self._widgets["lbl_channel"] = self.lbl_channel
        self.channel_combo = QComboBox()
        self.channel_combo.addItem(self.tr("channel_stdio"), "stdio")
        self.channel_combo.addItem(self.tr("channel_tcp_client"), "tcp-client")
        self.channel_combo.addItem(self.tr("channel_tcp_server"), "tcp-server")
        index = self.channel_combo.findData(self.config.get("channel", "stdio"))
        self.channel_combo.setCurrentIndex(max(0, index))
        self.channel_combo.currentIndexChanged.connect(self._on_channel_changed)
        row.addWidget(self.lbl_channel)
        row.addWidget(self.channel_combo, 1)
        engine_layout.addLayout(row)

        self.engine_stack = QWidget()
        stack_layout = QVBoxLayout(self.engine_stack)
        stack_layout.setContentsMargins(0, 0, 0, 0)

        row = QHBoxLayout()
        self.engine_path_edit = QLineEdit(self.config.get("engine_path", ""))
        self.engine_path_edit.setPlaceholderText("katago.exe / leelaz.exe / ...")
        self.btn_browse_engine = QPushButton()
        self.btn_browse_engine.clicked.connect(self._browse_engine)
        row.addWidget(self.engine_path_edit, 1)
        row.addWidget(self.btn_browse_engine)
        stack_layout.addLayout(row)

        self.engine_args_edit = QLineEdit(self.config.get("engine_args", ""))
        self.engine_args_edit.setPlaceholderText("gtp -model model.bin.gz -config gtp.cfg")
        stack_layout.addWidget(self.engine_args_edit)

        row = QHBoxLayout()
        self.engine_host_edit = QLineEdit(self.config.get("engine_host", "127.0.0.1"))
        self.engine_port_spin = QSpinBox()
        self.engine_port_spin.setRange(1, 65535)
        self.engine_port_spin.setValue(int(self.config.get("engine_port") or 8000))
        row.addWidget(self.engine_host_edit, 1)
        row.addWidget(self.engine_port_spin)
        stack_layout.addLayout(row)
        engine_layout.addWidget(self.engine_stack)

        row = QHBoxLayout()
        self.btn_connect = QPushButton()
        self.btn_connect.setObjectName("primary")
        self.btn_connect.clicked.connect(self._toggle_engine)
        self.btn_settings = QPushButton()
        self.btn_settings.clicked.connect(self._open_settings)
        row.addWidget(self.btn_connect)
        row.addWidget(self.btn_settings)
        engine_layout.addLayout(row)

        self.lbl_engine_state = QLabel()
        self.lbl_engine_state.setWordWrap(True)
        engine_layout.addWidget(self.lbl_engine_state)
        left_layout.addWidget(engine_group)

        # Options group
        options_group = QGroupBox()
        self._widgets["options_group"] = options_group
        options_layout = QVBoxLayout(options_group)
        self.chk_go_byoyomi = QCheckBox()
        self.chk_go_byoyomi.setChecked(bool(self.config.get("use_go_byoyomi")))
        self.chk_go_byoyomi.toggled.connect(self._apply_options)
        options_layout.addWidget(self.chk_go_byoyomi)

        row = QHBoxLayout()
        self.chk_data_transfer = QCheckBox()
        self.chk_data_transfer.setChecked(bool(self.config.get("use_data_transfer_time")))
        self.data_transfer_spin = QSpinBox()
        self.data_transfer_spin.setRange(0, 600)
        self.data_transfer_spin.setValue(int(self.config.get("data_transfer_time") or 1))
        self.chk_data_transfer.toggled.connect(self._apply_options)
        self.data_transfer_spin.valueChanged.connect(self._apply_options)
        row.addWidget(self.chk_data_transfer)
        row.addWidget(self.data_transfer_spin)
        row.addStretch(1)
        options_layout.addLayout(row)

        row = QHBoxLayout()
        self.chk_ai_cal = QCheckBox()
        self.chk_ai_cal.setChecked(bool(self.config.get("use_ai_cal_time")))
        self.ai_cal_spin = QSpinBox()
        self.ai_cal_spin.setRange(1, 3600)
        self.ai_cal_spin.setValue(int(self.config.get("ai_cal_time") or 5))
        self.chk_ai_cal.toggled.connect(self._apply_options)
        self.ai_cal_spin.valueChanged.connect(self._apply_options)
        row.addWidget(self.chk_ai_cal)
        row.addWidget(self.ai_cal_spin)
        row.addStretch(1)
        options_layout.addLayout(row)

        self.chk_analyze = QCheckBox()
        self.chk_analyze.setChecked(bool(self.config.get("use_analyze", True)))
        self.chk_analyze.toggled.connect(self._apply_options)
        options_layout.addWidget(self.chk_analyze)

        self.chk_test_mode = QCheckBox()
        self.chk_test_mode.toggled.connect(self._on_test_mode)
        options_layout.addWidget(self.chk_test_mode)
        left_layout.addWidget(options_group)

        row = QHBoxLayout()
        self.btn_ai_board = QPushButton()
        self.btn_ai_board.clicked.connect(self._show_ai_board)
        self.btn_fox_board = QPushButton()
        self.btn_fox_board.clicked.connect(self._show_fox_board)
        self.btn_shell = QPushButton()
        self.btn_shell.clicked.connect(self._show_shell)
        row.addWidget(self.btn_ai_board)
        row.addWidget(self.btn_fox_board)
        row.addWidget(self.btn_shell)
        left_layout.addLayout(row)
        left_layout.addStretch(1)
        splitter.addWidget(left)

        # ---------------- right: communication log ----------------
        log_group = QGroupBox()
        self._widgets["log_group"] = log_group
        log_layout = QVBoxLayout(log_group)

        row = QHBoxLayout()
        self.chk_timestamp = QCheckBox()
        self.chk_timestamp.setChecked(bool(self.config.get("timestamp_in_log", True)))
        self.chk_timestamp.toggled.connect(self._on_log_options)
        self.chk_save_log = QCheckBox()
        self.chk_save_log.setChecked(bool(self.config.get("save_log", False)))
        self.chk_save_log.toggled.connect(self._on_log_options)
        self.btn_clear_log = QPushButton()
        self.btn_clear_log.clicked.connect(self._clear_log)
        self.btn_open_log_dir = QPushButton()
        self.btn_open_log_dir.clicked.connect(self._open_log_dir)
        row.addWidget(self.chk_timestamp)
        row.addWidget(self.chk_save_log)
        row.addStretch(1)
        row.addWidget(self.btn_clear_log)
        row.addWidget(self.btn_open_log_dir)
        log_layout.addLayout(row)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(MAX_LOG_BLOCKS)
        font = QFont("Consolas", 9)
        font.setStyleHint(QFont.Monospace)
        self.log_view.setFont(font)
        log_layout.addWidget(self.log_view, 1)
        splitter.addWidget(log_group)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([430, 900])
        root.addWidget(splitter)

        self.status_label = QLabel()
        self.statusBar().addWidget(self.status_label, 1)
        self.statusBar().setStyleSheet("QStatusBar{min-height:22px;}")

    def _build_menus(self):
        menu_bar = self.menuBar()
        self.menu_work = menu_bar.addMenu("")
        self.menu_comm = menu_bar.addMenu("")
        self.menu_board = menu_bar.addMenu("")
        self.menu_tools = menu_bar.addMenu("")
        self.menu_help = menu_bar.addMenu("")

        self.action_start_fox = QAction("", self)
        self.action_start_fox.triggered.connect(self._start_fox)
        self.action_stop_fox = QAction("", self)
        self.action_stop_fox.triggered.connect(self._stop_fox)
        self.menu_work.addAction(self.action_start_fox)
        self.menu_work.addAction(self.action_stop_fox)

        self.action_connect = QAction("", self)
        self.action_connect.triggered.connect(self._toggle_engine)
        self.menu_comm.addAction(self.action_connect)
        self.action_settings = QAction("", self)
        self.action_settings.triggered.connect(self._open_settings)
        self.menu_comm.addAction(self.action_settings)

        self.action_ai_board = QAction("", self)
        self.action_ai_board.triggered.connect(self._show_ai_board)
        self.action_fox_board = QAction("", self)
        self.action_fox_board.triggered.connect(self._show_fox_board)
        self.menu_board.addAction(self.action_ai_board)
        self.menu_board.addAction(self.action_fox_board)

        self.action_shell = QAction("", self)
        self.action_shell.triggered.connect(self._show_shell)
        self.action_query_status = QAction("", self)
        self.action_query_status.triggered.connect(self._query_status)
        self.action_clear_log = QAction("", self)
        self.action_clear_log.triggered.connect(self._clear_log)
        self.action_open_log = QAction("", self)
        self.action_open_log.triggered.connect(self._open_log_dir)
        self.menu_tools.addAction(self.action_shell)
        self.menu_tools.addAction(self.action_query_status)
        self.menu_tools.addSeparator()
        self.menu_tools.addAction(self.action_clear_log)
        self.menu_tools.addAction(self.action_open_log)

        self.action_help = QAction("", self)
        self.action_help.triggered.connect(self._show_help)
        self.action_about = QAction("", self)
        self.action_about.triggered.connect(self._show_about)
        self.action_language = QAction("", self)
        self.action_language.triggered.connect(self._toggle_language)
        self.action_exit = QAction("", self)
        self.action_exit.triggered.connect(self.close)
        self.menu_help.addAction(self.action_help)
        self.menu_help.addAction(self.action_about)
        self.menu_help.addSeparator()
        self.menu_help.addAction(self.action_language)
        self.menu_help.addAction(self.action_exit)

    # ================================================================== i18n
    def _retranslate(self):
        tr = self.tr
        self.setWindowTitle(tr("app_title"))
        self.menu_work.setTitle(tr("menu_work"))
        self.menu_comm.setTitle(tr("menu_comm"))
        self.menu_board.setTitle(tr("menu_board"))
        self.menu_tools.setTitle(tr("menu_tools"))
        self.menu_help.setTitle(tr("menu_help"))

        self.action_start_fox.setText(tr("action_start_fox"))
        self.action_stop_fox.setText(tr("action_stop_fox"))
        self.action_connect.setText(tr("action_connect"))
        self.action_settings.setText(tr("action_settings"))
        self.action_shell.setText(tr("action_shell"))
        self.action_ai_board.setText(tr("action_ai_board"))
        self.action_fox_board.setText(tr("action_fox_board"))
        self.action_query_status.setText(tr("action_query_status"))
        self.action_clear_log.setText(tr("action_clear_log"))
        self.action_open_log.setText(tr("action_open_log"))
        self.action_help.setText(tr("action_help"))
        self.action_about.setText(tr("action_about"))
        self.action_language.setText(tr("action_lang"))
        self.action_exit.setText(tr("action_exit"))

        self._widgets["fox_group"].setTitle(tr("group_fox"))
        self._widgets["engine_group"].setTitle(tr("group_engine"))
        self._widgets["options_group"].setTitle(tr("group_options"))
        self._widgets["log_group"].setTitle(tr("group_log"))

        self.lbl_fox_port.setText(tr("label_port"))
        self.lbl_channel.setText(tr("label_channel"))
        self.btn_start_fox.setText(tr("btn_start"))
        self.btn_stop_fox.setText(tr("btn_stop"))
        self.btn_connect.setText(tr("btn_connect"))
        self.btn_settings.setText(tr("action_settings"))
        self.btn_browse_engine.setText(tr("btn_browse"))
        self.btn_ai_board.setText(tr("action_ai_board"))
        self.btn_fox_board.setText(tr("action_fox_board"))
        self.btn_shell.setText(tr("action_shell"))
        self.btn_clear_log.setText(tr("btn_clear"))
        self.btn_open_log_dir.setText(tr("action_open_log"))
        self.chk_go_byoyomi.setText(tr("opt_go_byoyomi"))
        self.chk_data_transfer.setText(tr("opt_data_transfer"))
        self.chk_ai_cal.setText(tr("opt_ai_cal_time"))
        self.chk_analyze.setText(tr("opt_analysis"))
        self.chk_test_mode.setText(tr("opt_test_mode"))
        self.chk_timestamp.setText(tr("opt_timestamp"))
        self.chk_save_log.setText(tr("opt_save_log"))
        self.channel_combo.setItemText(0, tr("channel_stdio"))
        self.channel_combo.setItemText(1, tr("channel_tcp_client"))
        self.channel_combo.setItemText(2, tr("channel_tcp_server"))
        self.lbl_engine_state.setText(tr("state_engine_off"))
        self.lbl_fox_state.setText(tr("state_fox_off"))
        self._update_connect_button()

    def _toggle_language(self):
        self.lang.toggle()
        self.config["language"] = self.lang.code
        save_config(self.config)
        self.controller.apply_config(self.config)
        self._retranslate()

    # ================================================================== geometry
    def _restore_geometry(self):
        geometry = self.config.get("window_geometry")
        if geometry:
            try:
                self.restoreGeometry(bytes.fromhex(geometry))
            except Exception:
                pass

    def closeEvent(self, event):
        try:
            self.config["window_geometry"] = bytes(self.saveGeometry()).hex()
            self.config["fox_port"] = int(self.fox_port_spin.value())
            self.config["engine_path"] = self.engine_path_edit.text().strip()
            self.config["engine_args"] = self.engine_args_edit.text().strip()
            self.config["engine_host"] = self.engine_host_edit.text().strip()
            self.config["engine_port"] = int(self.engine_port_spin.value())
            self.config["channel"] = self.channel_combo.currentData()
            save_config(self.config)
        except Exception:
            pass
        self.controller.shutdown()
        super().closeEvent(event)

    # ================================================================== actions
    def _on_channel_changed(self):
        channel = self.channel_combo.currentData()
        for widget in (self.engine_path_edit, self.engine_args_edit, self.btn_browse_engine):
            widget.setVisible(channel == "stdio")
        for widget in (self.engine_host_edit, self.engine_port_spin):
            widget.setVisible(channel in ("tcp-client", "tcp-server"))
        self.config["channel"] = channel

    def _browse_engine(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 AI 引擎", "",
                                              "可执行文件 (*.exe);;所有文件 (*.*)")
        if path:
            self.engine_path_edit.setText(path)

    def _apply_options(self):
        self.config.update({
            "use_go_byoyomi": self.chk_go_byoyomi.isChecked(),
            "use_data_transfer_time": self.chk_data_transfer.isChecked(),
            "data_transfer_time": int(self.data_transfer_spin.value()),
            "use_ai_cal_time": self.chk_ai_cal.isChecked(),
            "ai_cal_time": int(self.ai_cal_spin.value()),
            "use_analyze": self.chk_analyze.isChecked(),
        })
        save_config(self.config)
        self.controller.apply_config(self.config)

    def _on_log_options(self):
        self.config["timestamp_in_log"] = self.chk_timestamp.isChecked()
        self.config["save_log"] = self.chk_save_log.isChecked()
        save_config(self.config)
        self.controller.apply_config(self.config)

    def _collect_engine_config(self):
        self.config.update({
            "channel": self.channel_combo.currentData(),
            "engine_path": self.engine_path_edit.text().strip(),
            "engine_args": self.engine_args_edit.text().strip(),
            "engine_host": self.engine_host_edit.text().strip() or "127.0.0.1",
            "engine_port": int(self.engine_port_spin.value()),
            "fox_port": int(self.fox_port_spin.value()),
        })
        self.controller.apply_config(self.config)
        return build_engine_command(self.config)

    def _toggle_engine(self):
        if self.controller.transport is not None:
            self._disconnect_engine()
        else:
            self._connect_engine()

    def _connect_engine(self):
        command = self._collect_engine_config()
        if self.config["channel"] == "stdio" and not command:
            QMessageBox.warning(self, "FoxGTP-Py", "请先选择 AI 引擎程序并填写参数")
            return
        ok, message = self.controller.start_engine()
        self.controller.logbook.info(message)
        if not ok:
            QMessageBox.warning(self, "FoxGTP-Py", message)
        self._update_connect_button()

    def _disconnect_engine(self):
        self.controller.stop_engine()
        self._update_connect_button()

    def _update_connect_button(self):
        connected = self.controller.transport is not None
        self.btn_connect.setText(self.tr("btn_disconnect") if connected
                                 else self.tr("btn_connect"))
        self.action_connect.setText(self.tr("action_disconnect") if connected
                                    else self.tr("action_connect"))
        self.btn_connect.setEnabled(True)

    def _start_fox(self):
        self.config["fox_port"] = int(self.fox_port_spin.value())
        self.controller.apply_config(self.config)
        ok, message = self.controller.start_fox()
        if not ok:
            QMessageBox.warning(self, "FoxGTP-Py", message)
            return
        self.btn_start_fox.setEnabled(False)
        self.btn_stop_fox.setEnabled(True)
        self.action_start_fox.setEnabled(False)
        self.action_stop_fox.setEnabled(True)

    def _stop_fox(self):
        self.controller.stop_fox()
        self.btn_start_fox.setEnabled(True)
        self.btn_stop_fox.setEnabled(False)
        self.action_start_fox.setEnabled(True)
        self.action_stop_fox.setEnabled(False)

    def _open_settings(self):
        dialog = SettingsDialog(self, self.config, self.tr,
                                on_apply=self._apply_settings)
        if dialog.exec_() == dialog.Accepted:
            self._apply_settings()

    def _apply_settings(self):
        self.controller.apply_config(self.config)
        self.fox_port_spin.setValue(int(self.config.get("fox_port") or 6000))
        self.channel_combo.setCurrentIndex(
            max(0, self.channel_combo.findData(self.config.get("channel", "stdio"))))
        self.engine_path_edit.setText(self.config.get("engine_path", ""))
        self.engine_args_edit.setText(self.config.get("engine_args", ""))
        self.engine_host_edit.setText(self.config.get("engine_host", "127.0.0.1"))
        self.engine_port_spin.setValue(int(self.config.get("engine_port") or 8000))
        self.chk_go_byoyomi.setChecked(bool(self.config.get("use_go_byoyomi")))
        self.chk_data_transfer.setChecked(bool(self.config.get("use_data_transfer_time")))
        self.data_transfer_spin.setValue(int(self.config.get("data_transfer_time") or 0))
        self.chk_ai_cal.setChecked(bool(self.config.get("use_ai_cal_time")))
        self.ai_cal_spin.setValue(int(self.config.get("ai_cal_time") or 5))
        self.chk_analyze.setChecked(bool(self.config.get("use_analyze", True)))
        self.chk_timestamp.setChecked(bool(self.config.get("timestamp_in_log", True)))
        self.chk_save_log.setChecked(bool(self.config.get("save_log", False)))
        self.lang.set(self.config.get("language", "zh"))
        self._retranslate()
        if self.ai_board_window is not None:
            self.ai_board_window.board.show_coordinates = bool(
                self.config.get("show_coordinates", True))
            self.ai_board_window.board.show_move_numbers = bool(
                self.config.get("show_move_numbers", False))
            self.ai_board_window.update()

    def _show_shell(self):
        if self.shell_window is None:
            self.shell_window = ShellDialog(self, self.controller, self.tr)
        self.shell_window.show()
        self.shell_window.raise_()

    def _show_ai_board(self):
        if self.ai_board_window is None:
            self.ai_board_window = BoardWindow(
                self, self.tr("ai_board_title"), self.tr,
                with_analysis=True, interactive=self.chk_test_mode.isChecked())
            self.ai_board_window.clicked.connect(self._on_ai_board_click)
            self.ai_board_window.right_clicked.connect(self._on_ai_board_right_click)
            geometry = self.config.get("ai_board_geometry")
            if geometry:
                try:
                    self.ai_board_window.restoreGeometry(bytes.fromhex(geometry))
                except Exception:
                    pass
        self.ai_board_window.show()
        self.ai_board_window.raise_()
        if self.board_payload:
            self.ai_board_window.update_state(self.board_payload)

    def _show_fox_board(self):
        if self.fox_board_window is None:
            self.fox_board_window = BoardWindow(self, self.tr("fox_board_title"), self.tr,
                                                with_analysis=False)
            geometry = self.config.get("fox_board_geometry")
            if geometry:
                try:
                    self.fox_board_window.restoreGeometry(bytes.fromhex(geometry))
                except Exception:
                    pass
        self.fox_board_window.show()
        self.fox_board_window.raise_()
        if self.board_payload:
            self.fox_board_window.update_state(self.board_payload)

    def _on_test_mode(self, checked):
        self.config["test_mode"] = checked
        if checked:
            self.controller.test_new_game(19, 6.5, 0)
            self._show_ai_board()
        if self.ai_board_window is not None:
            self.ai_board_window.set_interactive(checked)

    def _on_ai_board_click(self, x, y):
        if not self.chk_test_mode.isChecked():
            return
        color = self.controller.state.turn_color()
        self.controller.test_play(x, y, color)

    def _on_ai_board_right_click(self, x, y):
        if not self.chk_test_mode.isChecked():
            return
        self.controller.test_genmove(self.controller.state.turn_color())

    def _query_status(self):
        self.controller.request_fox_status()
        self.controller.logbook.info("已向野狐发送 $AFSTATUS 查询当前状态")

    def _clear_log(self):
        self.log_view.clear()

    def _open_log_dir(self):
        directory = self.config.get("log_dir") or "logs"
        if not os.path.isabs(directory):
            directory = os.path.join(os.getcwd(), directory)
        os.makedirs(directory, exist_ok=True)
        try:
            os.startfile(directory)          # noqa: S606 - intended
        except Exception:
            QMessageBox.information(self, "FoxGTP-Py", directory)

    def _show_help(self):
        HelpDialog(self, self.tr("help_title"), HELP_TEXT).exec_()

    def _show_about(self):
        HelpDialog(self, self.tr("about_title"), ABOUT_TEXT).exec_()

    # ================================================================== events
    def _on_event(self, topic, payload):
        if topic == "log":
            self._append_log(payload)
        elif topic == "engine":
            self._on_engine_event(payload)
        elif topic == "fox":
            self._on_fox_event(payload)
        elif topic == "board":
            self.board_payload = payload
            if self.ai_board_window is not None:
                self.ai_board_window.update_state(payload)
            if self.fox_board_window is not None:
                self.fox_board_window.update_state(payload)
        elif topic == "candidates":
            self._on_candidates(payload)
        elif topic == "result":
            for window in (self.ai_board_window, self.fox_board_window):
                if window is not None:
                    window.clear_all()
            self.log_view.appendPlainText("*** %s" % payload.get("readable", ""))
        elif topic == "time":
            self._refresh_status()
        elif topic == "error":
            self.log_view.appendHtml(
                '<span style="color:%s;">***** %s</span>'
                % (theme.ERROR, html.escape(str(payload.get("text", "")))))

    def _append_log(self, payload):
        channel = payload.get("channel", "gtp")
        direction = payload.get("direction", INFO)
        text = html.escape(payload.get("text", ""))
        if direction == ERROR:
            color = theme.ERROR
        elif channel == "fox":
            color = theme.ACCENT if direction == IN else "#7FD1FF"
        else:
            color = theme.TEXT if direction == IN else theme.MUTED
        if direction == INFO:
            color = theme.MUTED
        self.log_view.appendHtml('<span style="color:%s;">%s</span>' % (color, text))

    def _on_engine_event(self, payload):
        running = payload.get("running")
        ready = payload.get("ready")
        description = payload.get("description", "")
        if not running:
            self.lbl_engine_state.setText("%s — %s" % (self.tr("state_engine_off"), description))
            self.lbl_engine_state.setStyleSheet("color: %s;" % theme.MUTED)
        elif ready:
            self.lbl_engine_state.setText("%s — %s" % (self.tr("state_engine_ready"), description))
            self.lbl_engine_state.setStyleSheet("color: %s;" % theme.GOOD)
        else:
            self.lbl_engine_state.setText("%s — %s"
                                          % (self.tr("state_engine_connected"), description))
            self.lbl_engine_state.setStyleSheet("color: %s;" % theme.WARN)
        self._update_connect_button()

    def _on_fox_event(self, payload):
        listening = payload.get("listening")
        connected = payload.get("connected")
        peer = payload.get("peer") or ""
        if connected:
            self.lbl_fox_state.setText("%s — %s" % (self.tr("state_fox_connected"), peer))
            self.lbl_fox_state.setStyleSheet("color: %s;" % theme.GOOD)
        elif listening:
            self.lbl_fox_state.setText(self.tr("state_fox_waiting"))
            self.lbl_fox_state.setStyleSheet("color: %s;" % theme.WARN)
        else:
            self.lbl_fox_state.setText(self.tr("state_fox_off"))
            self.lbl_fox_state.setStyleSheet("color: %s;" % theme.MUTED)
        self.btn_start_fox.setEnabled(not listening)
        self.btn_stop_fox.setEnabled(bool(listening))
        self.action_start_fox.setEnabled(not listening)
        self.action_stop_fox.setEnabled(bool(listening))

    def _on_candidates(self, payload):
        candidates = payload.get("candidates") or []
        self.board_payload["candidates"] = candidates
        self.board_payload["winrate"] = payload.get("winrate")
        self.board_payload["score"] = payload.get("score")
        if self.ai_board_window is not None:
            self.ai_board_window.update_state(self.board_payload)
            winrate = payload.get("winrate")
            if winrate is not None:
                black = winrate if self.controller.state.ai_color == "B" else 1.0 - winrate
                self.ai_board_window.add_winrate_point(
                    self.controller.state.last_move_no, black, payload.get("score"))

    def _refresh_status(self):
        state = self.controller.status()
        engine_text = "就绪" if state["engine_ready"] else "未连接"
        fox_text = "已连接" if state["fox_connected"] else (
            "等待连接" if state["fox_listening"] else "未监听")
        winrate = state["winrate"]
        text = ("引擎 %s | 野狐 %s | %d路 贴目%s | AI执%s | 手数%d | 同步%d/%d | 胜率%s"
                % (engine_text, fox_text, state["board_size"], state["komi"],
                   state["ai_color"], state["last_move"],
                   state["engine_events"], state["events"],
                   ("%.1f%%" % (winrate * 100)) if winrate is not None else "—"))
        self.status_label.setText(text)
