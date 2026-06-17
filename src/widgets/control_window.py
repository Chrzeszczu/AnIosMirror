from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QCheckBox
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from src.backends import android as ad


class MirrorControlWindow(QWidget):
    stop_requested = pyqtSignal(str)
    aot_changed = pyqtSignal(str, bool)
    status_message = pyqtSignal(str, str)

    def __init__(self, device_name, serial, aot_default=True, media_dir=None, parent=None):
        super().__init__(parent)
        self._serial = serial
        self._device_name = device_name
        self._media_dir = media_dir
        self._hwnd = None

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(210, 170)
        self.setStyleSheet("""
            MirrorControlWindow {
                background-color: #2d2d2d;
                border: 1px solid #555;
                border-radius: 4px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        lbl = QLabel(device_name)
        lbl.setStyleSheet("font-weight: bold; font-size: 11px; color: #eee;")
        layout.addWidget(lbl)

        self.aot = QCheckBox("Always on Top")
        self.aot.setStyleSheet("color: #ccc; font-size: 10px;")
        self.aot.setChecked(aot_default)
        self.aot.stateChanged.connect(self._on_aot)
        layout.addWidget(self.aot)

        self.screenshot_btn = QPushButton("Screenshot")
        self.screenshot_btn.clicked.connect(self._take_screenshot)
        layout.addWidget(self.screenshot_btn)

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
        if self.aot.isChecked():
            ad.set_window_always_on_top_by_hwnd(hwnd, True)
            self._set_self_topmost(True)

    def set_aot(self, enabled):
        self._apply_aot(enabled, emit=False)

    def closeEvent(self, event):
        event.ignore()

    def _on_aot(self, state):
        self._apply_aot(state == 2, emit=True)

    def _apply_aot(self, enabled, emit=True):
        self.aot.blockSignals(True)
        self.aot.setChecked(enabled)
        self.aot.blockSignals(False)

        if self._hwnd is not None:
            ad.set_window_always_on_top_by_hwnd(self._hwnd, enabled)
        self._set_self_topmost(enabled)

        if emit:
            self.aot_changed.emit(self._serial, enabled)

    def _set_self_topmost(self, enabled):
        visible = self.isVisible()
        self.hide()
        flags = self.windowFlags()
        if enabled:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        if visible:
            self.show()
            QTimer.singleShot(0, self._track)

    def _take_screenshot(self):
        if not self._media_dir or self._hwnd is None:
            return
        self.screenshot_btn.setEnabled(False)
        filepath, error = ad.take_screenshot(self._serial, self._media_dir)
        if filepath:
            self.status_message.emit(self._serial, f"Screenshot saved")
        else:
            self.status_message.emit(self._serial, f"Screenshot failed: {error}")
        self.screenshot_btn.setEnabled(True)

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
