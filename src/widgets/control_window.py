import ctypes
from ctypes import wintypes
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox, QComboBox
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QSettings
from src.backends import android as ad

_user32 = ctypes.windll.user32

WINEVENTPROC = ctypes.WINFUNCTYPE(
    None, wintypes.HANDLE, wintypes.DWORD,
    wintypes.HWND, wintypes.LONG, wintypes.LONG,
    wintypes.DWORD, wintypes.DWORD,
)
_EVENT_OBJECT_LOCATIONCHANGE = 0x800B
_WINEVENT_OUTOFCONTEXT = 0x0001

_user32.SetWinEventHook.argtypes = [
    wintypes.UINT, wintypes.UINT, wintypes.HMODULE,
    WINEVENTPROC, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
]
_user32.SetWinEventHook.restype = wintypes.HANDLE


class MirrorControlWindow(QWidget):
    stop_requested = pyqtSignal(str)
    aot_changed = pyqtSignal(str, bool)
    status_message = pyqtSignal(str, str)
    quality_changed = pyqtSignal(str, str)
    _hwnd_moved = pyqtSignal()

    _NORMAL_W = 210
    _NORMAL_H = 275
    _COLLAPSED_W = 36
    _COLLAPSED_H = 24

    def __init__(self, device_name, serial, media_dir=None,
                 quality_options=None, current_quality=None,
                 platform="android", parent=None):
        super().__init__(parent)
        self._serial = serial
        self._device_name = device_name
        self._media_dir = media_dir
        self._quality_options = quality_options or []
        self._current_quality = current_quality
        self._platform = platform
        self._hwnd = None
        self._recording = False
        self._paused = False
        self._collapsed = False
        self._qsettings = QSettings("AnIosMirror", "AnIosMirror")
        self._side = self._qsettings.value(f"control/{serial}/side", "right")
        self._hook = None
        self._hook_proc = None
        self._rec_start_time = None
        self._ios_segments = []

        self._hwnd_moved.connect(self._track)

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(self._NORMAL_W, self._NORMAL_H)
        self.setStyleSheet("""
            MirrorControlWindow {
                background-color: #2d2d2d;
                border: 1px solid #555;
                border-radius: 4px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        # Content that gets hidden on collapse
        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(4)

        lbl = QLabel(device_name)
        lbl.setStyleSheet("font-weight: bold; font-size: 11px; color: #eee;")
        content_layout.addWidget(lbl)

        saved_aot = self._qsettings.value(f"control/{serial}/aot", "true")
        aot_checked = saved_aot == "true" if isinstance(saved_aot, str) else bool(saved_aot)
        self.aot = QCheckBox("Always on Top")
        self.aot.setStyleSheet("color: #ccc; font-size: 10px;")
        self.aot.setChecked(aot_checked)
        self.aot.stateChanged.connect(self._on_aot)
        content_layout.addWidget(self.aot)

        self.screenshot_btn = QPushButton("Screenshot")
        self.screenshot_btn.clicked.connect(self._take_screenshot)
        content_layout.addWidget(self.screenshot_btn)

        rec_row = QHBoxLayout()
        self.rec_btn = QPushButton("Record")
        self.rec_btn.clicked.connect(self._toggle_recording)
        rec_row.addWidget(self.rec_btn)
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self._toggle_pause)
        if self._platform != "android":
            self.pause_btn.hide()
        rec_row.addWidget(self.pause_btn)
        content_layout.addLayout(rec_row)

        self._rec_time_label = QLabel("00:00")
        self._rec_time_label.setStyleSheet("color: #e44; font-size: 11px; font-weight: bold;")
        self._rec_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._rec_time_label.hide()
        content_layout.addWidget(self._rec_time_label)

        self._rec_timer = QTimer(self)
        self._rec_timer.timeout.connect(self._update_rec_time)
        self._rec_timer.setInterval(1000)

        # Quality row
        q_row = QHBoxLayout()
        q_label = QLabel("Quality:")
        q_label.setStyleSheet("color: #ccc; font-size: 10px;")
        q_row.addWidget(q_label)
        self.quality_combo = QComboBox()
        self.quality_combo.setStyleSheet("font-size: 9px;")
        self.quality_combo.blockSignals(True)
        if self._quality_options:
            self.quality_combo.addItems(self._quality_options)
            if self._current_quality:
                idx = self.quality_combo.findText(self._current_quality)
                if idx >= 0:
                    self.quality_combo.setCurrentIndex(idx)
        self.quality_combo.blockSignals(False)
        self.quality_combo.currentTextChanged.connect(self._on_quality_changed)
        q_row.addWidget(self.quality_combo, 1)
        content_layout.addLayout(q_row)

        content_layout.addStretch()

        self.stop_btn = QPushButton("Stop Mirror")
        self.stop_btn.clicked.connect(lambda: self.stop_requested.emit(self._serial))
        content_layout.addWidget(self.stop_btn)

        # Bottom row: hide checkbox + side selector
        bottom_row = QHBoxLayout()
        self.hide_cb = QCheckBox("Hide Menu")
        self.hide_cb.setStyleSheet("color: #999; font-size: 9px;")
        self.hide_cb.stateChanged.connect(self._on_hide_changed)
        bottom_row.addWidget(self.hide_cb)
        bottom_row.addStretch()
        side_lbl = QLabel("Side:")
        side_lbl.setStyleSheet("color: #999; font-size: 9px;")
        bottom_row.addWidget(side_lbl)
        self.side_combo = QComboBox()
        self.side_combo.addItems(["Right", "Left"])
        self.side_combo.setStyleSheet("font-size: 9px;")
        idx = self.side_combo.findText(self._side.capitalize())
        if idx >= 0:
            self.side_combo.setCurrentIndex(idx)
        self.side_combo.currentTextChanged.connect(self._on_side_changed)
        bottom_row.addWidget(self.side_combo)
        content_layout.addLayout(bottom_row)

        layout.addWidget(self._content)

        # Expand button for collapsed state
        self._expand_btn = QPushButton("☰")
        self._expand_btn.setFixedSize(26, 22)
        self._expand_btn.setStyleSheet("font-size: 14px; color: #ccc;")
        self._expand_btn.clicked.connect(self._toggle_collapse)
        self._expand_btn.hide()
        layout.addWidget(self._expand_btn, 0, Qt.AlignmentFlag.AlignCenter)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._track)
        self._timer.start(500)

    def set_hwnd(self, hwnd):
        self._uninstall_move_hook()
        self._hwnd = hwnd
        self._install_move_hook(hwnd)
        self._track()
        if self.aot.isChecked():
            ad.set_window_always_on_top_by_hwnd(hwnd, True)
            self._set_self_topmost(True)

    def _install_move_hook(self, target_hwnd):
        try:
            proc = WINEVENTPROC(lambda hHook, event, hwnd, idObject, idChild, dwEventThread, dwmsEventTime: (
                self._hwnd_moved.emit()
                if hwnd == target_hwnd and idObject == 0 else None
            ))
            self._hook_proc = proc
            self._hook = _user32.SetWinEventHook(
                _EVENT_OBJECT_LOCATIONCHANGE, _EVENT_OBJECT_LOCATIONCHANGE,
                0, proc, 0, 0, _WINEVENT_OUTOFCONTEXT,
            )
        except Exception:
            self._hook = None

    def _uninstall_move_hook(self):
        if self._hook:
            try:
                _user32.UnhookWinEvent(self._hook)
            except Exception:
                pass
            self._hook = None
        self._hook_proc = None

    def set_aot(self, enabled):
        self._apply_aot(enabled, emit=False)

    def closeEvent(self, event):
        event.ignore()

    def _on_aot(self, state):
        self._qsettings.setValue(f"control/{self._serial}/aot", state == 2)
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

    def _on_hide_changed(self, state):
        self._collapsed = state == 2
        if self._collapsed:
            self.layout().setContentsMargins(1, 1, 1, 1)
            self._content.hide()
            self._expand_btn.show()
            self.setFixedSize(self._COLLAPSED_W, self._COLLAPSED_H)
        else:
            self.layout().setContentsMargins(4, 4, 4, 4)
            self._expand_btn.hide()
            self._content.show()
            self.setFixedSize(self._NORMAL_W, self._NORMAL_H)
        self._track()

    def _toggle_collapse(self):
        self.hide_cb.blockSignals(True)
        self.hide_cb.setChecked(not self._collapsed)
        self.hide_cb.blockSignals(False)
        self._on_hide_changed(2 if not self._collapsed else 0)

    def _on_side_changed(self, text):
        self._side = text.lower()
        self._qsettings.setValue(f"control/{self._serial}/side", self._side)
        if not self._collapsed:
            self._track()

    def _on_quality_changed(self, text):
        if text:
            self.quality_changed.emit(self._serial, text)

    def _take_screenshot(self):
        if not self._media_dir or self._hwnd is None:
            return
        self.screenshot_btn.setEnabled(False)
        if self._platform == "android":
            filepath, error = ad.take_screenshot(self._serial, self._media_dir)
        else:
            filepath, error = ad.capture_window_screenshot(self._hwnd, self._media_dir)
        if filepath:
            self.status_message.emit(self._serial, "Screenshot saved")
        else:
            self.status_message.emit(self._serial, f"Screenshot failed: {error}")
        self.screenshot_btn.setEnabled(True)

    def _toggle_recording(self):
        if not self._recording:
            if not self._media_dir:
                return
            self._ios_segments = []
            if self._platform == "android":
                filepath, error = ad.start_recording(self._serial, self._media_dir)
            else:
                filepath, error = ad.start_window_recording(self._hwnd, self._media_dir)
            if error:
                self.status_message.emit(self._serial, f"Record failed: {error}")
                return
            self._recording = True
            self._paused = False
            self._rec_start_time = __import__('time').time()
            self.rec_btn.setText("Stop Recording")
            self.pause_btn.setEnabled(True)
            self.pause_btn.setText("Pause")
            self._rec_time_label.setText("00:00")
            self._rec_time_label.show()
            self._rec_timer.start()
            self.status_message.emit(self._serial, "Recording started")
        else:
            if self._platform == "android":
                result, error = ad.stop_recording(self._serial)
            else:
                result, error = ad.stop_window_recording(self._hwnd)
                if result:
                    self._ios_segments.append(result)
                    if len(self._ios_segments) > 1:
                        result = list(self._ios_segments)
                    else:
                        result = self._ios_segments[0]
                self._ios_segments = []
            self._recording = False
            self._paused = False
            self._rec_start_time = None
            self._pause_start = 0.0
            self.rec_btn.setText("Record")
            self.pause_btn.setEnabled(False)
            self.pause_btn.setText("Pause")
            self._rec_timer.stop()
            self._rec_time_label.hide()
            if isinstance(result, list):
                self.status_message.emit(self._serial, f"Saved {len(result)} segment(s)")
            elif result:
                self.status_message.emit(self._serial, "Recording saved")
            else:
                self.status_message.emit(self._serial, f"Record failed: {error}")

    def _toggle_pause(self):
        if self._platform == "ios":
            if not self._paused:
                path, _ = ad.stop_window_recording(self._hwnd)
                if path:
                    self._ios_segments.append(path)
                self._paused = True
                self._pause_start = __import__('time').time()
                self.pause_btn.setText("Resume")
                self._rec_timer.stop()
                self.status_message.emit(self._serial, "Recording paused")
            else:
                path, error = ad.start_window_recording(self._hwnd, self._media_dir)
                if error:
                    self.status_message.emit(self._serial, f"Resume failed: {error}")
                else:
                    self._paused = False
                    self._rec_start_time += __import__('time').time() - self._pause_start
                    self.pause_btn.setText("Pause")
                    self._rec_timer.start()
                    self.status_message.emit(self._serial, "Recording resumed")
        else:
            if not self._paused:
                local, error = ad.pause_recording(self._serial)
                if local:
                    self._paused = True
                    self._pause_start = __import__('time').time()
                    self.pause_btn.setText("Resume")
                    self._rec_timer.stop()
                    self.status_message.emit(self._serial, "Recording paused")
                else:
                    self.status_message.emit(self._serial, f"Pause failed: {error}")
            else:
                local, error = ad.resume_recording(self._serial, self._media_dir)
                if local:
                    self._paused = False
                    self._rec_start_time += __import__('time').time() - self._pause_start
                    self.pause_btn.setText("Pause")
                    self._rec_timer.start()
                    self.status_message.emit(self._serial, "Recording resumed")
                else:
                    self.status_message.emit(self._serial, f"Resume failed: {error}")

    def _update_rec_time(self):
        if not self._rec_start_time:
            return
        elapsed = int(__import__('time').time() - self._rec_start_time)
        self._rec_time_label.setText(f"{elapsed // 60:02d}:{elapsed % 60:02d}")

    def _track(self):
        if not self._hwnd:
            return
        rect = ad.get_hwnd_rect(self._hwnd)
        if rect is None:
            self.stop_requested.emit(self._serial)
            return
        mw = self.width()
        mh = self.height()
        if self._side == "right":
            x = rect["x"] + rect["w"] + 8
        else:
            x = rect["x"] - mw - 8
        y = rect["y"] + (5 if self._collapsed else 30)
        self.move(x, y)
        try:
            if ctypes.windll.user32.GetForegroundWindow() == self._hwnd:
                ctypes.windll.user32.SetWindowPos(
                    int(self.winId()),
                    0, 0, 0, 0, 0,
                    0x0001 | 0x0002 | 0x0010
                )
        except Exception:
            pass

    def cleanup(self):
        self._timer.stop()
        self._uninstall_move_hook()
        if self._recording:
            if self._platform == "android":
                ad.stop_recording(self._serial)
            else:
                path, _ = ad.stop_window_recording(self._hwnd)
                if path:
                    self._ios_segments.append(path)
                self._ios_segments = []
        self._hwnd = None
        self.hide()
