"""
SakuraGTP 对话框集合。

所有设置类模态对话框从 ui_main 抽到此处，行为与原实现一致；
每个函数接收主窗口 app 作为参数（依赖其 cfg / engine / fox / api_server
等属性与方法），避免循环导入。
"""

import secrets

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QMessageBox, QFormLayout, QSlider, QListWidget,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

from config import save_config
from sci_widgets import GlowButton, GlowLineEdit, GlowComboBox, GlowCheckBox


# ---------- 心跳设置 ----------
def open_heartbeat_dialog(app):
    dlg = QDialog(app)
    dlg.setWindowTitle("心跳设置")
    dlg.resize(400, 200)

    layout = QFormLayout(dlg)

    chk = GlowCheckBox("启用心跳检测")
    chk.setChecked(app.cfg.get("heartbeat_enabled", False))
    layout.addRow("", chk)

    interval_edit = GlowLineEdit(str(app.cfg.get("heartbeat_interval", 30)))
    layout.addRow("心跳间隔（秒）:", interval_edit)

    timeout_edit = GlowLineEdit(str(app.cfg.get("heartbeat_timeout", 10)))
    layout.addRow("超时判定（秒）:", timeout_edit)

    def on_save():
        app.cfg["heartbeat_enabled"] = chk.isChecked()
        try:
            app.cfg["heartbeat_interval"] = int(interval_edit.text())
        except ValueError:
            app.cfg["heartbeat_interval"] = 30
        try:
            app.cfg["heartbeat_timeout"] = int(timeout_edit.text())
        except ValueError:
            app.cfg["heartbeat_timeout"] = 10
        save_config(app.cfg)
        app.engine.set_heartbeat(
            app.cfg["heartbeat_enabled"],
            app.cfg["heartbeat_interval"],
            app.cfg["heartbeat_timeout"],
        )
        app._log_comm("心跳设置已保存")
        dlg.accept()

    btn = GlowButton("保存")
    btn.clicked.connect(on_save)
    layout.addRow("", btn)

    dlg.exec_()


# ---------- 断线重连设置 ----------
def open_reconnect_dialog(app):
    dlg = QDialog(app)
    dlg.setWindowTitle("断线重连设置")
    dlg.resize(400, 200)

    layout = QFormLayout(dlg)

    chk = GlowCheckBox("启用自动重连")
    chk.setChecked(app.cfg.get("auto_reconnect", True))
    layout.addRow("", chk)

    interval_edit = GlowLineEdit(str(app.cfg.get("reconnect_interval", 5)))
    layout.addRow("重连间隔（秒）:", interval_edit)

    def on_save():
        app.cfg["auto_reconnect"] = chk.isChecked()
        try:
            app.cfg["reconnect_interval"] = int(interval_edit.text())
        except ValueError:
            app.cfg["reconnect_interval"] = 5
        save_config(app.cfg)
        app.fox.set_auto_reconnect(
            app.cfg["auto_reconnect"],
            app.cfg["reconnect_interval"],
        )
        app._log_comm("断线重连设置已保存")
        dlg.accept()

    btn = GlowButton("保存")
    btn.clicked.connect(on_save)
    layout.addRow("", btn)

    dlg.exec_()


# ---------- API Token 设置 ----------
def open_token_dialog(app):
    dlg = QDialog(app)
    dlg.setWindowTitle("API Token 设置")
    dlg.resize(500, 200)

    layout = QFormLayout(dlg)

    chk = GlowCheckBox("启用 Token 认证")
    chk.setChecked(app.cfg.get("api_token_enabled", False))
    layout.addRow("", chk)

    token_edit = GlowLineEdit(app.cfg.get("api_token", ""))
    token_edit.setPlaceholderText("留空则自动生成")
    layout.addRow("Token:", token_edit)

    def on_generate():
        token_edit.setText("sakura_" + secrets.token_hex(16))

    btn_gen = GlowButton("自动生成")
    btn_gen.clicked.connect(on_generate)
    layout.addRow("", btn_gen)

    def on_save():
        app.cfg["api_token_enabled"] = chk.isChecked()
        token = token_edit.text().strip()
        if not token and app.cfg["api_token_enabled"]:
            token = "sakura_" + secrets.token_hex(16)
            token_edit.setText(token)
        app.cfg["api_token"] = token
        save_config(app.cfg)
        app.api_server.set_token(app.cfg["api_token_enabled"], token)
        QMessageBox.information(dlg, "Token", f"当前 Token:\n{token}")
        dlg.accept()

    btn = GlowButton("保存")
    btn.clicked.connect(on_save)
    layout.addRow("", btn)

    dlg.exec_()


# ---------- 自动跑谱设置 ----------
def open_contribute_dialog(app):
    dlg = QDialog(app)
    dlg.setWindowTitle("自动跑谱设置")
    dlg.resize(600, 300)

    layout = QFormLayout(dlg)

    chk = GlowCheckBox("启用自动跑谱")
    chk.setChecked(app.cfg.get("auto_contribute", False))
    layout.addRow("", chk)

    cmd_edit = GlowLineEdit(app.cfg.get("contribute_command", ""))
    cmd_edit.setPlaceholderText(
        'katago.exe contribute -config contribute_example.cfg'
    )
    layout.addRow("跑谱命令:", cmd_edit)

    idle_edit = GlowLineEdit(str(app.cfg.get("contribute_idle_seconds", 300)))
    layout.addRow("空闲多少秒后启动:", idle_edit)

    stop_chk = GlowCheckBox("有对局立刻停止跑谱")
    stop_chk.setChecked(app.cfg.get("contribute_stop_on_game", True))
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
        app.cfg["auto_contribute"] = chk.isChecked()
        app.cfg["contribute_command"] = cmd_edit.text().strip()
        try:
            app.cfg["contribute_idle_seconds"] = int(idle_edit.text())
        except ValueError:
            app.cfg["contribute_idle_seconds"] = 300
        app.cfg["contribute_stop_on_game"] = stop_chk.isChecked()
        save_config(app.cfg)
        app._log_comm("自动跑谱设置已保存")
        dlg.accept()

    btn = GlowButton("保存")
    btn.clicked.connect(on_save)
    layout.addRow("", btn)

    dlg.exec_()


# ---------- 常用 GTP 指令管理 ----------
def manage_snippets(app):
    dlg = QDialog(app)
    dlg.setWindowTitle("管理常用 GTP 指令")
    dlg.resize(600, 400)

    layout = QVBoxLayout(dlg)
    layout.addWidget(QLabel("指令列表（每条一行）:"))

    snippet_list = QListWidget()
    for s in app.cfg.get("gtp_snippets", []):
        snippet_list.addItem(s)
    layout.addWidget(snippet_list, stretch=1)

    edit_row = QHBoxLayout()
    snippet_edit = GlowLineEdit()
    snippet_edit.setPlaceholderText("输入一条 GTP 命令，例如 kata-set-param maxTime 5")
    edit_row.addWidget(snippet_edit, stretch=1)

    def _save_snippets(snippets):
        app.cfg["gtp_snippets"] = snippets
        save_config(app.cfg)
        app._refresh_snippet_combo()

    def _add():
        text = snippet_edit.text().strip()
        if not text:
            return
        snippets = app.cfg.get("gtp_snippets", [])
        if not isinstance(snippets, list):
            snippets = []
        if text not in snippets:
            snippets.append(text)
            _save_snippets(snippets)
            snippet_list.addItem(text)
        snippet_edit.clear()

    def _delete():
        item = snippet_list.currentItem()
        if not item:
            return
        text = item.text()
        snippets = app.cfg.get("gtp_snippets", [])
        if not isinstance(snippets, list):
            snippets = []
        if text in snippets:
            snippets.remove(text)
            _save_snippets(snippets)
            snippet_list.takeItem(snippet_list.row(item))

    btn_add = GlowButton("添加")
    btn_add.clicked.connect(_add)
    edit_row.addWidget(btn_add)
    layout.addLayout(edit_row)

    btn_row = QHBoxLayout()
    btn_del = GlowButton("删除选中")
    btn_del.clicked.connect(_delete)
    btn_row.addWidget(btn_del)
    btn_row.addStretch()
    btn_close = GlowButton("关闭")
    btn_close.clicked.connect(dlg.accept)
    btn_row.addWidget(btn_close)
    layout.addLayout(btn_row)

    dlg.exec_()
