import ctypes
from ctypes import wintypes
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QCheckBox
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from src.backends import android as ad


class MirrorControlBar(QWidget):
    stop_requested = pyqtSignal(str)
    aot_changed = pyqtSignal(str, bool)

    def __init__(self, device_name, serial, aot_default=False, parent=None):
        super().__init__(parent)
        self._serial = serial
        self._device_name = device_name
        self._hwnd = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(180, 28)

        self.setStyleSheet("""
            MirrorControlBar {
                background-color: #2a2a2a;
                border: 1px solid #555;
                border-radius: 3px;
            }
            QLabel { color: #eee; font-size: 9px; }
            QCheckBox { color: #ccc; font-size: 9px; }
            QPushButton { font-size: 9px; padding: 0px 6px; }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)

        lbl = QLabel(device_name[:20])
        layout.addWidget(lbl)
        layout.addStretch()

        self.aot = QCheckBox("AoT")
        self.aot.setChecked(aot_default)
        self.aot.stateChanged.connect(self._on_aot)
        layout.addWidget(self.aot)

        stop = QPushButton("Stop")
        stop.setFixedWidth(36)
        stop.clicked.connect(lambda: self.stop_requested.emit(self._serial))
        layout.addWidget(stop)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._track)
        self._timer.start(500)

    def set_hwnd(self, hwnd):
        self._hwnd = hwnd
        self._track()

    def set_aot(self, enabled):
        self.aot.blockSignals(True)
        self.aot.setChecked(enabled)
        self.aot.blockSignals(False)

    def _on_aot(self, state):
        self.aot_changed.emit(self._serial, state == 2)

    def _track(self):
        if not self._hwnd:
            return
        rect = ad.get_hwnd_rect(self._hwnd)
        if rect is None:
            self.stop_requested.emit(self._serial)
            return
        x = rect["x"] + rect["w"] - self.width() - 5
        y = rect["y"] + 5
        self.move(x, y)

    def cleanup(self):
        self._timer.stop()
        self._hwnd = None
        self.hide()
