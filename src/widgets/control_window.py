from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QCheckBox
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from src.backends import android as ad


class MirrorControlWindow(QWidget):
    stop_requested = pyqtSignal(str)
    aot_changed = pyqtSignal(str, bool)

    def __init__(self, device_name, serial, aot_default=False, parent=None):
        super().__init__(parent)
        self._serial = serial
        self._device_name = device_name
        self._hwnd = None

        self.setWindowTitle(f"Mirror: {device_name[:30]}")
        self.setWindowFlags(Qt.WindowType.Tool)
        self.setFixedSize(200, 130)

        layout = QVBoxLayout(self)

        lbl = QLabel(device_name)
        lbl.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(lbl)

        self.aot = QCheckBox("Always on Top")
        self.aot.setChecked(aot_default)
        self.aot.stateChanged.connect(self._on_aot)
        layout.addWidget(self.aot)

        layout.addStretch()

        self.stop_btn = QPushButton("Stop Mirror")
        self.stop_btn.clicked.connect(lambda: self.stop_requested.emit(self._serial))
        layout.addWidget(self.stop_btn)

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
        enabled = state == 2
        if self._hwnd is not None:
            ad.set_window_always_on_top_by_hwnd(self._hwnd, enabled)
        self.aot_changed.emit(self._serial, enabled)

    def _track(self):
        if not self._hwnd:
            return
        rect = ad.get_hwnd_rect(self._hwnd)
        if rect is None:
            self.stop_requested.emit(self._serial)
            return
        x = rect["x"] + rect["w"] + 8
        y = rect["y"] + 30
        self.move(x, y)

    def cleanup(self):
        self._timer.stop()
        self._hwnd = None
        self.hide()
