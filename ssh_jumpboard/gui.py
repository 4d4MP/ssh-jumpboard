"""Qt based graphical interface for ssh-jumpboard."""
from __future__ import annotations

import re
import threading
from datetime import datetime, timezone
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from . import history
from .config import Config, load_config, save_config, set_alias, remove_alias
from .errors import AgentUnavailable, ConfigNotInitialized, ValidationError
from .key_agent import detect_agent, ensure_key_loaded, make_askpass_wrapper

HOST_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")
from .runner import open_external_terminal, run_chain_in_current_tty
from .ssh_builder import build_jump_command, build_target_command, preview_chain


class PassphraseDialog(QDialog):
    """Dialog requesting a passphrase from the user."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("SSH Passphrase")
        self._choice = "agent"
        layout = QVBoxLayout(self)
        self.info = QLabel("We never store your passphrase.")
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.info)
        layout.addWidget(self.pass_edit)

        self.agent_box = QCheckBox("Load into agent for this session")
        self.agent_box.setChecked(True)
        self.askpass_box = QCheckBox("Use one-time passphrase (ASKPASS)")
        self.askpass_box.setChecked(False)
        self.agent_box.stateChanged.connect(self._sync_options)
        self.askpass_box.stateChanged.connect(self._sync_options)
        layout.addWidget(self.agent_box)
        layout.addWidget(self.askpass_box)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _sync_options(self) -> None:
        sender = self.sender()
        if sender is self.agent_box and self.agent_box.isChecked():
            self.askpass_box.setChecked(False)
        elif sender is self.askpass_box and self.askpass_box.isChecked():
            self.agent_box.setChecked(False)
        if self.agent_box.isChecked():
            self._choice = "agent"
        elif self.askpass_box.isChecked():
            self._choice = "askpass"

    @property
    def choice(self) -> str:
        return self._choice

    def get_passphrase(self) -> tuple[Optional[str], str]:
        if self.exec() == QDialog.Accepted:
            return self.pass_edit.text(), self.choice
        return None, self.choice


class SettingsDialog(QDialog):
    """Settings dialog for jump configuration."""

    def __init__(self, cfg: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Settings")
        self.user_edit = QLineEdit(cfg.jump_user)
        self.host_edit = QLineEdit(cfg.jump_ip)
        self.external_box = QCheckBox("Launch in external terminal")
        self.external_box.setChecked(cfg.launch_external_terminal)

        layout = QFormLayout(self)
        layout.addRow("Jump user", self.user_edit)
        layout.addRow("Jump host/IP", self.host_edit)
        layout.addRow("", self.external_box)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.validateAndPersist)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def validateAndPersist(self) -> None:
        user = self.user_edit.text().strip()
        host = self.host_edit.text().strip()
        if not user:
            QMessageBox.warning(self, "Error", "Jump user must not be empty")
            return
        if not host or not HOST_PATTERN.match(host):
            QMessageBox.warning(self, "Error", "Jump host/IP must be valid")
            return
        self.cfg.jump_user = user
        self.cfg.jump_ip = host
        self.cfg.launch_external_terminal = self.external_box.isChecked()
        save_config(self.cfg)
        self.accept()


class AliasDialog(QDialog):
    """Dialog for managing aliases."""

    def __init__(self, cfg: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Aliases")
        layout = QVBoxLayout(self)
        self.alias_list = QListWidget()
        layout.addWidget(self.alias_list)
        self.refresh()
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        add_button = buttons.addButton("Add", QDialogButtonBox.ActionRole)
        rm_button = buttons.addButton("Remove", QDialogButtonBox.ActionRole)
        add_button.clicked.connect(self.add_alias)
        rm_button.clicked.connect(self.remove_alias)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def refresh(self) -> None:
        self.alias_list.clear()
        for name, ip in sorted(self.cfg.aliases.items()):
            self.alias_list.addItem(f"{name} → {ip}")

    def add_alias(self) -> None:
        name, ok = QInputDialog.getText(self, "Alias name", "Alias name")
        if not ok or not name:
            return
        ip, ok = QInputDialog.getText(self, "Alias target", "Target host/IP")
        if not ok or not ip:
            return
        try:
            set_alias(self.cfg, name, ip)
        except ValidationError as exc:
            QMessageBox.warning(self, "Error", str(exc))
            return
        self.refresh()

    def remove_alias(self) -> None:
        if not self.cfg.aliases:
            return
        name, ok = QInputDialog.getItem(
            self,
            "Remove alias",
            "Select alias",
            sorted(self.cfg.aliases.keys()),
            editable=False,
        )
        if not ok or not name:
            return
        try:
            remove_alias(self.cfg, name)
        except ValidationError as exc:
            QMessageBox.warning(self, "Error", str(exc))
            return
        self.refresh()


class RecentList(QListWidget):
    """Recent target list with context menu."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._open_menu)

    def _open_menu(self, pos) -> None:
        item = self.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        connect_action = menu.addAction("Connect")
        copy_action = menu.addAction("Copy")
        remove_action = menu.addAction("Remove")
        action = menu.exec(self.mapToGlobal(pos))
        if action == connect_action:
            self.parent().setTargetAndConnect(item.data(Qt.UserRole))
        elif action == copy_action:
            QApplication.clipboard().setText(item.data(Qt.UserRole))
        elif action == remove_action:
            self.parent().remove_recent_item(item)


class TargetInput(QLineEdit):
    """Line edit with Enter shortcut."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.returnPressed.connect(self._on_return)

    def _on_return(self) -> None:
        self.parent().handleConnect()


class MainWindow(QMainWindow):
    """Primary window for ssh-jumpboard."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SSH Jumpboard")
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.cfg: Optional[Config] = None

        central = QWidget()
        layout = QGridLayout(central)

        self.target_label = QLabel("Target")
        self.target_input = TargetInput(self)
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.handleConnect)

        self.recent_list = RecentList(self)
        self.recent_list.itemActivated.connect(lambda item: self.setTargetAndConnect(item.data(Qt.UserRole)))

        layout.addWidget(self.target_label, 0, 0)
        layout.addWidget(self.target_input, 0, 1)
        layout.addWidget(self.connect_button, 0, 2)
        layout.addWidget(QLabel("Recent"), 0, 3)
        layout.addWidget(self.recent_list, 1, 3, 2, 1)

        self.preview_label = QLabel()
        self.preview_label.setWordWrap(True)
        layout.addWidget(self.preview_label, 1, 0, 1, 3)

        self.setCentralWidget(central)

        self._build_menus()
        self._first_run_setup()
        self._refresh_recent()
        self._update_status("Ready")

    def _build_menus(self) -> None:
        menubar = self.menuBar()
        settings_menu = menubar.addMenu("Settings")
        settings_action = QAction("Settings…", self)
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(self.open_settings)
        settings_menu.addAction(settings_action)

        alias_menu = menubar.addMenu("Aliases")
        alias_action = QAction("Manage…", self)
        alias_action.triggered.connect(self.open_aliases)
        alias_menu.addAction(alias_action)

        help_menu = menubar.addMenu("Help")
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

        focus_action = QAction(self)
        focus_action.setShortcut(QKeySequence("Ctrl+L"))
        focus_action.triggered.connect(self.target_input.setFocus)
        self.addAction(focus_action)

    def _first_run_setup(self) -> None:
        try:
            self.cfg = load_config()
        except ConfigNotInitialized:
            cfg = Config(jump_user="", jump_ip="")
            dialog = SettingsDialog(cfg, self)
            if dialog.exec() == QDialog.Accepted:
                self.cfg = cfg
            else:
                self.close()
                return
        self._refresh_completer()

    def _refresh_completer(self) -> None:
        if not self.cfg:
            return
        completer = QCompleter(list(self.cfg.aliases.keys()))
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.target_input.setCompleter(completer)

    def _refresh_recent(self) -> None:
        if not self.cfg:
            return
        self.recent_list.clear()
        items = history.list_recent(self.cfg)
        for entry in items:
            item = QListWidgetItem(f"{entry.target_ip} ({self._format_timeago(entry.ts)})")
            item.setData(Qt.UserRole, entry.target_ip)
            self.recent_list.addItem(item)

    def _update_status(self, message: str) -> None:
        jump = f"{self.cfg.jump_user}@{self.cfg.jump_ip}" if self.cfg else "(not set)"
        self.status.showMessage(f"Jump: {jump} — {message}")

    def open_settings(self) -> None:
        if not self.cfg:
            return
        dialog = SettingsDialog(self.cfg, self)
        if dialog.exec() == QDialog.Accepted:
            self._refresh_completer()
            self._update_status("Settings saved")

    def open_aliases(self) -> None:
        if not self.cfg:
            return
        dialog = AliasDialog(self.cfg, self)
        dialog.exec()
        self._refresh_completer()
        self._refresh_recent()

    def show_about(self) -> None:
        QMessageBox.information(self, "About", "ssh-jumpboard\nTwo hop SSH utility")

    def handleConnect(self) -> None:
        if not self.cfg:
            return
        target = self.target_input.text().strip()
        if not target:
            QMessageBox.warning(self, "Error", "Please enter a target host")
            return
        if target in self.cfg.aliases:
            target = self.cfg.aliases[target]
        if not HOST_PATTERN.match(target):
            QMessageBox.warning(self, "Error", "Invalid target host or IP")
            return
        preview = preview_chain(self.cfg, target)
        self.preview_label.setText("Will run:\n" + preview)
        self._update_status("Connecting…")

        status = detect_agent()
        askpass_ctx = None
        if not (status.has_agent and status.has_loaded_keys):
            dialog = PassphraseDialog(self)
            pwd, choice = dialog.get_passphrase()
            if pwd is None:
                self._update_status("Cancelled")
                return
            if choice == "askpass" or not status.has_agent:
                askpass_ctx = make_askpass_wrapper(pwd)
            else:
                pass_holder = {"value": pwd}

                def prompt() -> Optional[str]:
                    value = pass_holder.get("value", "")
                    pass_holder["value"] = ""
                    return value

                try:
                    ensure_result = ensure_key_loaded(prompt)
                except AgentUnavailable as exc:
                    self._update_status(str(exc))
                    return
                askpass_ctx = ensure_result.askpass

        jump_cmd = build_jump_command(self.cfg)
        target_cmd = build_target_command(target)

        def run_commands() -> None:
            if self.cfg.launch_external_terminal:
                cmdline = " && ".join([" ".join(jump_cmd), " ".join(target_cmd)])
                exit_code = open_external_terminal(cmdline)
            else:
                exit_code = run_chain_in_current_tty(jump_cmd, target_cmd, askpass_ctx)
            if exit_code == 0:
                history.record(self.cfg, target)
                QTimer.singleShot(0, lambda: self._on_success())
            else:
                QTimer.singleShot(0, lambda: self._update_status(f"Failed (exit {exit_code})"))

        threading.Thread(target=run_commands, daemon=True).start()

    def _on_success(self) -> None:
        self._update_status("Connected")
        self._refresh_recent()

    def setTargetAndConnect(self, target: str) -> None:
        self.target_input.setText(target)
        self.handleConnect()

    def remove_recent_item(self, item: QListWidgetItem) -> None:
        if not self.cfg:
            return
        target = item.data(Qt.UserRole)
        self.cfg.history = [entry for entry in self.cfg.history if entry.get("target_ip") != target]
        save_config(self.cfg)
        self._refresh_recent()

    def _format_timeago(self, ts) -> str:
        now = datetime.now(timezone.utc)
        delta = now - ts
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return f"{seconds}s ago"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        return f"{days}d ago"


def launch() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    app.exec()


if __name__ == "__main__":  # pragma: no cover
    launch()
