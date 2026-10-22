"""Native desktop settings dialog.

The dialog intentionally does not navigate the web view: replacing the SPA with
a local ``file://`` page used to destroy the React state (and, with a
non-persistent web profile, the login).  Settings are applied live instead.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .config import ConfigError, DesktopConfig, normalize_server_url
from .version import __version__

_DIALOG_STYLE = """
QDialog { background: #0b0e13; }
QLabel { color: #c9cfda; font-size: 12px; }
QLabel#Title { color: #ffffff; font-size: 17px; font-weight: bold; }
QLabel#Subtitle { color: #8b94a7; font-size: 11.5px; }
QLabel#Error { color: #fda4af; font-size: 11.5px; }
QLabel#Hint { color: #7c8698; font-size: 11px; }
QLineEdit {
    background: #11151c; color: #e8eaef; border: 1px solid rgba(255,255,255,0.12);
    border-radius: 8px; padding: 8px 10px; font-size: 13px;
}
QLineEdit:focus { border-color: rgba(232,176,106,0.7); }
QCheckBox { color: #c9cfda; font-size: 12.5px; }
QPushButton {
    background: rgba(255,255,255,0.08); color: #e8eaef;
    border: 1px solid rgba(255,255,255,0.14); border-radius: 9px;
    padding: 8px 18px; font-size: 13px;
}
QPushButton:hover { background: rgba(255,255,255,0.16); }
QPushButton#Primary {
    background: #e8b06a; color: #17120b; border: none; font-weight: bold;
}
QPushButton#Primary:hover { background: #f0be7d; }
"""


class SettingsDialog(QDialog):
    """Server address, cache budget and self-signed HTTPS switch."""

    def __init__(
        self,
        config: DesktopConfig,
        parent: QWidget | None = None,
        *,
        allow_cancel: bool = True,
    ):
        super().__init__(parent)
        self._allow_cancel = allow_cancel
        self.setWindowTitle("StrmAction 设置")
        self.setModal(True)
        self.setMinimumWidth(460)
        self.setStyleSheet(_DIALOG_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(6)

        title = QLabel("StrmAction 桌面端")
        title.setObjectName("Title")
        layout.addWidget(title)

        subtitle = QLabel("原生内嵌播放，进度自动回传；登录在网页内完成。")
        subtitle.setObjectName("Subtitle")
        layout.addWidget(subtitle)
        layout.addSpacing(14)

        layout.addWidget(QLabel("服务器地址"))
        self.server_edit = QLineEdit(config.server_url)
        self.server_edit.setPlaceholderText("https://media.example.com")
        layout.addWidget(self.server_edit)

        hint = QLabel("必须带 http:// 或 https://；结尾的 / 可省略。")
        hint.setObjectName("Hint")
        layout.addWidget(hint)
        layout.addSpacing(10)

        layout.addWidget(QLabel("预读缓存上限（MB）"))
        self.cache_edit = QLineEdit(str(config.cache_limit_mb))
        self.cache_edit.setPlaceholderText("128")
        layout.addWidget(self.cache_edit)

        cache_hint = QLabel("0 关闭预读；非 0 时按 16–2048MB 执行。")
        cache_hint.setObjectName("Hint")
        layout.addWidget(cache_hint)
        layout.addSpacing(12)

        self.self_signed_check = QCheckBox("允许自签名 HTTPS 证书")
        self.self_signed_check.setChecked(config.allow_self_signed_https)
        layout.addWidget(self.self_signed_check)

        cert_hint = QLabel(
            "开启后对服务器、片源 CDN 等全部 HTTPS 连接跳过证书校验，存在中间人风险。"
        )
        cert_hint.setObjectName("Hint")
        cert_hint.setWordWrap(True)
        layout.addWidget(cert_hint)
        layout.addSpacing(12)

        self.error_label = QLabel("")
        self.error_label.setObjectName("Error")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 8, 0, 0)
        version_label = QLabel(f"v{__version__}")
        version_label.setObjectName("Hint")
        buttons.addWidget(version_label)
        buttons.addStretch()

        if allow_cancel:
            self.cancel_button = QPushButton("取消")
            self.cancel_button.clicked.connect(self.reject)
            buttons.addWidget(self.cancel_button)

        self.save_button = QPushButton("保存")
        self.save_button.setObjectName("Primary")
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self._on_save)
        buttons.addWidget(self.save_button)

        layout.addLayout(buttons)

    # -- helpers --------------------------------------------------------
    def values(self) -> dict:
        return {
            "server_url": self.server_edit.text().strip(),
            "cache_limit_mb": self.cache_edit.text().strip(),
            "allow_self_signed_https": self.self_signed_check.isChecked(),
        }

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(True)

    def _on_save(self) -> None:
        try:
            normalize_server_url(self.server_edit.text())
        except ConfigError as exc:
            self._show_error(str(exc))
            return

        raw_cache = self.cache_edit.text().strip() or "128"
        if not raw_cache.isdigit():
            self._show_error("缓存上限必须是 0–2048 之间的整数（MB）。")
            return
        cache = int(raw_cache)
        if cache > 2048 or (0 < cache < 16):
            self._show_error("缓存上限必须是 0，或 16–2048 之间的整数（MB）。")
            return

        self.error_label.setVisible(False)
        self.accept()

    def reject(self) -> None:  # noqa: D401 - Qt override
        if not self._allow_cancel:
            return
        super().reject()

    def closeEvent(self, event) -> None:
        # First run must end with a usable server address.
        if not self._allow_cancel:
            event.ignore()
            self._show_error("请先填写服务器地址并保存。")
            return
        super().closeEvent(event)
