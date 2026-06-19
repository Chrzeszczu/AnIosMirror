import sys
import os
import json
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem, QGroupBox,
    QProgressBar, QMessageBox, QDialog, QLineEdit, QComboBox, QInputDialog,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSettings
from PyQt6.QtGui import QGuiApplication

from src.downloader import check_tools, download_tools, get_tool_path
from src.backends import android as ad
from src.backends import ios as ios_module
from src.backends.ios import AirPlayReceiver
from src.widgets.pair_dialog import PairDialog
from src.widgets.control_window import MirrorControlWindow

TOOLS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tools")
MEDIA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "media")


class DeviceItem:
    def __init__(self, info, platform_type):
        self.info = info
        self.platform_type = platform_type

    def label(self):
        name = self.info.get("name", "Unknown")
        ip = self.info.get("ip", self.info.get("serial", "?"))
        return f"{name} ({ip})"


class ScanWorker(QThread):
    finished = pyqtSignal(list)
    progress = pyqtSignal(str)

    def run(self):
        try:
            subnets = ad.get_all_subnets()
            net_info = " ".join([f"{s[2]}:{s[1]}" for s in subnets])
            self.progress.emit(f"Scanning subnets: {net_info}")
            devices = ad.scan_network()
            self.finished.emit(devices)
        except Exception as e:
            self.progress.emit(f"Scan error: {e}")
            self.finished.emit([])


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AnIosMirror")
        self.setFixedWidth(520)

        self.android_devices = []
        self.airplay = AirPlayReceiver()
        self._scan_worker = None
        self._settings = QSettings("AnIosMirror", "AnIosMirror")
        self._favorites = []
        self._control_bars = {}
        self._ios_control_bar = None
        self._quality_presets = {}
        self._last_quality = "medium"
        self._ios_quality_presets = {}
        self._ios_last_quality = "medium"

        self._build_ui()
        self._load_favorites()
        self._load_quality_settings()
        self._load_ios_quality_settings()
        QTimer.singleShot(0, self._restore_geometry)
        self._check_tools()

        self._mirror_status_timer = QTimer()
        self._mirror_status_timer.timeout.connect(self._update_mirror_buttons)
        self._mirror_status_timer.start(2000)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(12)

        # Android section
        android_group = QGroupBox("Android")
        android_layout = QVBoxLayout(android_group)

        btn_row = QHBoxLayout()
        self.scan_btn = QPushButton("Scan Network")
        self.scan_btn.clicked.connect(self._scan_network)
        self.pair_btn = QPushButton("Pair with Pairing Code")
        self.pair_btn.clicked.connect(self._open_pair_dialog)
        btn_row.addWidget(self.scan_btn)
        btn_row.addWidget(self.pair_btn)
        android_layout.addLayout(btn_row)

        self.android_list = QListWidget()
        self.android_list.setMinimumHeight(120)
        android_layout.addWidget(self.android_list)

        manual_row = QHBoxLayout()
        self.manual_ip_input = QLineEdit()
        self.manual_ip_input.setPlaceholderText("192.168.1.x:5555")
        self.manual_connect_btn = QPushButton("Connect")
        self.manual_connect_btn.clicked.connect(self._manual_connect)
        manual_row.addWidget(self.manual_ip_input)
        manual_row.addWidget(self.manual_connect_btn)
        self.save_fav_btn = QPushButton("Save")
        self.save_fav_btn.setFixedWidth(50)
        self.save_fav_btn.clicked.connect(self._save_current_as_favorite)
        manual_row.addWidget(self.save_fav_btn)
        android_layout.addLayout(manual_row)

        btn_mirror_row = QHBoxLayout()
        self.mirror_android_btn = QPushButton("Start Mirror")
        self.mirror_android_btn.clicked.connect(self._mirror_android)
        self.mirror_android_btn.setEnabled(False)
        self.stop_android_btn = QPushButton("Stop Mirror")
        self.stop_android_btn.clicked.connect(self._stop_android)
        self.stop_android_btn.setEnabled(False)
        btn_mirror_row.addWidget(self.mirror_android_btn)
        btn_mirror_row.addWidget(self.stop_android_btn)
        android_layout.addLayout(btn_mirror_row)

        # Quality section
        quality_row = QHBoxLayout()
        quality_row.addWidget(QLabel("Quality:"))
        self.quality_combo = QComboBox()
        self.quality_combo.currentTextChanged.connect(self._on_quality_changed)
        quality_row.addWidget(self.quality_combo, 1)
        self.save_q_btn = QPushButton("Save")
        self.save_q_btn.setFixedWidth(50)
        self.save_q_btn.clicked.connect(self._save_quality_preset)
        quality_row.addWidget(self.save_q_btn)
        self.delete_q_btn = QPushButton("Del")
        self.delete_q_btn.setFixedWidth(40)
        self.delete_q_btn.clicked.connect(self._delete_quality_preset)
        quality_row.addWidget(self.delete_q_btn)
        android_layout.addLayout(quality_row)

        # Custom quality panel (hidden unless "Custom" selected)
        self.custom_panel = QWidget()
        custom_layout = QFormLayout(self.custom_panel)
        custom_layout.setContentsMargins(4, 2, 4, 2)
        self.q_bitrate = QComboBox()
        self.q_bitrate.addItems(["1M", "2M", "4M", "8M", "16M", "32M", "50M", "100M", "200M"])
        self.q_bitrate.setCurrentText("8M")
        self.q_maxsize = QComboBox()
        self.q_maxsize.addItems(["0", "480", "720", "1024", "1440", "1920", "2560"])
        self.q_maxsize.setCurrentText("0")
        self.q_fps = QComboBox()
        self.q_fps.addItems(["0", "10", "15", "24", "30", "48", "60", "90", "120"])
        self.q_fps.setCurrentText("30")
        self.q_encoder = QComboBox()
        self.q_encoder.addItems(["Auto", "h264", "h265"])
        custom_layout.addRow("Bitrate:", self.q_bitrate)
        custom_layout.addRow("Max Res:", self.q_maxsize)
        custom_layout.addRow("Max FPS:", self.q_fps)
        custom_layout.addRow("Encoder:", self.q_encoder)
        self.custom_panel.hide()
        android_layout.addWidget(self.custom_panel)

        self.android_status = QLabel("Status: idle")
        android_layout.addWidget(self.android_status)

        # Favorites section
        fav_group = QGroupBox("Favorites")
        fav_layout = QVBoxLayout(fav_group)
        fav_layout.setContentsMargins(4, 4, 4, 4)
        self.fav_list = QListWidget()
        self.fav_list.setMinimumHeight(80)
        self.fav_list.setMaximumHeight(160)
        fav_layout.addWidget(self.fav_list)
        fav_btn_row = QHBoxLayout()
        self.fav_connect_btn = QPushButton("Connect")
        self.fav_connect_btn.clicked.connect(self._connect_favorite)
        self.fav_remove_btn = QPushButton("Remove")
        self.fav_remove_btn.clicked.connect(self._remove_favorite)
        fav_btn_row.addWidget(self.fav_connect_btn)
        fav_btn_row.addWidget(self.fav_remove_btn)
        fav_layout.addLayout(fav_btn_row)
        android_layout.addWidget(fav_group)

        layout.addWidget(android_group)

        # iOS section
        ios_group = QGroupBox("iOS (AirPlay)")
        ios_layout = QVBoxLayout(ios_group)

        status_row = QHBoxLayout()
        status_row.addWidget(QLabel("AirPlay Receiver:"))
        self.airplay_status = QLabel("Stopped")
        self.airplay_status.setStyleSheet("color: gray; font-weight: bold;")
        status_row.addWidget(self.airplay_status)
        status_row.addStretch()
        ios_layout.addLayout(status_row)

        btn_row2 = QHBoxLayout()
        self.airplay_start_btn = QPushButton("Start Receiver")
        self.airplay_start_btn.clicked.connect(self._airplay_start)
        self.airplay_stop_btn = QPushButton("Stop Receiver")
        self.airplay_stop_btn.clicked.connect(self._airplay_stop)
        self.airplay_stop_btn.setEnabled(False)
        btn_row2.addWidget(self.airplay_start_btn)
        btn_row2.addWidget(self.airplay_stop_btn)
        ios_layout.addLayout(btn_row2)

        # iOS Quality section
        ios_q_row = QHBoxLayout()
        ios_q_row.addWidget(QLabel("Quality:"))
        self.ios_quality_combo = QComboBox()
        self.ios_quality_combo.currentTextChanged.connect(self._on_ios_quality_changed)
        ios_q_row.addWidget(self.ios_quality_combo, 1)
        self.ios_save_q_btn = QPushButton("Save")
        self.ios_save_q_btn.setFixedWidth(50)
        self.ios_save_q_btn.clicked.connect(self._save_ios_quality_preset)
        ios_q_row.addWidget(self.ios_save_q_btn)
        self.ios_delete_q_btn = QPushButton("Del")
        self.ios_delete_q_btn.setFixedWidth(40)
        self.ios_delete_q_btn.clicked.connect(self._delete_ios_quality_preset)
        ios_q_row.addWidget(self.ios_delete_q_btn)
        ios_layout.addLayout(ios_q_row)

        # iOS custom quality panel
        self.ios_custom_panel = QWidget()
        ios_custom_layout = QFormLayout(self.ios_custom_panel)
        ios_custom_layout.setContentsMargins(4, 2, 4, 2)
        self.ios_q_res = QComboBox()
        self.ios_q_res.addItems(["1920x1080@60", "1280x720@60", "1280x720@30", "854x480@24"])
        self.ios_q_fps = QComboBox()
        self.ios_q_fps.addItems(["30", "24", "60"])
        self.ios_q_fps.setCurrentText("30")
        self.ios_q_h265 = QComboBox()
        self.ios_q_h265.addItems(["No", "Yes"])
        ios_custom_layout.addRow("Resolution:", self.ios_q_res)
        ios_custom_layout.addRow("FPS:", self.ios_q_fps)
        ios_custom_layout.addRow("H.265:", self.ios_q_h265)
        self.ios_custom_panel.hide()
        ios_layout.addWidget(self.ios_custom_panel)

        ios_help = QLabel(
            "On iPhone: Control Center \u2192 Screen Mirroring \u2192 select AnIosMirror"
        )
        ios_help.setStyleSheet("color: #888; font-size: 11px;")
        ios_layout.addWidget(ios_help)
        layout.addWidget(ios_group)

        # Tools section
        tools_group = QGroupBox("Tools")
        tools_layout = QVBoxLayout(tools_group)
        self.tools_label = QLabel("Checking...")
        tools_layout.addWidget(self.tools_label)
        self.download_btn = QPushButton("Download Missing Tools")
        self.download_btn.clicked.connect(self._download_tools)
        tools_layout.addWidget(self.download_btn)
        self.dl_progress = QProgressBar()
        self.dl_progress.setVisible(False)
        tools_layout.addWidget(self.dl_progress)
        layout.addWidget(tools_group)

        self.android_list.currentRowChanged.connect(self._on_selection_changed)

    def _check_tools(self):
        missing = check_tools()
        if missing:
            self.tools_label.setText(f"Missing: {', '.join(missing)}")
            self.download_btn.setVisible(True)
        else:
            self.tools_label.setText("All tools ready \u2713")
            self.download_btn.setVisible(False)

    def _download_tools(self):
        self.dl_progress.setVisible(True)
        self.dl_progress.setRange(0, 0)
        self.download_btn.setEnabled(False)

        def progress(msg):
            self.tools_label.setText(msg)

        try:
            download_tools(progress)
            self._check_tools()
        except Exception as e:
            QMessageBox.critical(self, "Download Error", str(e))
        finally:
            self.dl_progress.setVisible(False)
            self.download_btn.setEnabled(True)

    def _load_favorites(self):
        import json
        raw = self._settings.value("favorites", "[]")
        if isinstance(raw, str):
            try:
                self._favorites = json.loads(raw)
            except Exception:
                self._favorites = []
        self._refresh_favorites_list()

    def _save_favorites(self):
        import json
        self._settings.setValue("favorites", json.dumps(self._favorites))
        self._refresh_favorites_list()

    def _refresh_favorites_list(self):
        if not hasattr(self, "fav_list") or self.fav_list is None:
            return
        self.fav_list.clear()
        for f in self._favorites:
            self.fav_list.addItem(f"{f['name']} ({f['ip']}:{f['port']})")

    def _save_current_as_favorite(self):
        addr = self.manual_ip_input.text().strip()
        if not addr:
            QMessageBox.warning(self, "Error", "Enter IP:port first")
            return
        if ":" not in addr:
            addr = f"{addr}:5555"
        ip, port = addr.rsplit(":", 1)
        port = int(port)
        name = ip
        for d in self.android_devices:
            if d.get("ip") == ip or d.get("serial", "").startswith(ip):
                name = d.get("name", ip)
                break
        for f in self._favorites:
            if f["ip"] == ip and f["port"] == port:
                self.android_status.setText(f"Already saved: {ip}:{port}")
                return
        self._favorites.append({"name": name, "ip": ip, "port": port})
        self._save_favorites()
        self.android_status.setText(f"Saved favorite: {name} ({ip}:{port})")

    def _connect_favorite(self):
        idx = self.fav_list.currentRow()
        if idx < 0 or idx >= len(self._favorites):
            return
        fav = self._favorites[idx]
        try:
            dev = ad.connect_device(fav["ip"], fav["port"])
            serial = f"{fav['ip']}:{fav['port']}"
            if serial not in {d["serial"] for d in self.android_devices}:
                self.android_devices.append(dev)
                self.android_list.addItem(f"{dev['name']} ({dev['ip']})")
            self.android_status.setText(f"Connected: {dev['name']}")
        except Exception as e:
            QMessageBox.critical(self, "Connection Error", str(e))

    def _remove_favorite(self):
        idx = self.fav_list.currentRow()
        if idx < 0 or idx >= len(self._favorites):
            return
        del self._favorites[idx]
        self._save_favorites()

    def _scan_network(self):
        self.scan_btn.setEnabled(False)
        self.android_list.clear()
        self.android_status.setText("Scanning...")

        self._scan_worker = ScanWorker()
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_worker.progress.connect(self.android_status.setText)
        self._scan_worker.start()

    def _on_scan_finished(self, devices):
        self.android_devices = devices
        self.android_list.clear()
        for d in devices:
            item = DeviceItem(d, "android")
            self.android_list.addItem(item.label())
        if not devices:
            self.android_status.setText(
                "No devices found. Try manual IP or USB cable: enable USB Debugging, "
                "connect USB, run '.\\tools\\adb.exe tcpip 5555', disconnect USB, then Scan."
            )
        else:
            self.android_status.setText(f"Found {len(devices)} device(s)")
        self.scan_btn.setEnabled(True)
        self._on_selection_changed()

    def _on_selection_changed(self):
        selected = self.android_list.currentRow() >= 0
        self.mirror_android_btn.setEnabled(selected)
        self.stop_android_btn.setEnabled(selected)

    # ── Quality ──────────────────────────────────────────

    def _load_quality_settings(self):
        self._last_quality = self._settings.value("quality/last", "medium")
        raw = self._settings.value("quality/saved", "{}")
        if isinstance(raw, str):
            try:
                self._quality_presets = json.loads(raw)
            except Exception:
                self._quality_presets = {}
        self._populate_quality_combo()
        self._restore_custom_values()

    def _restore_custom_values(self):
        br = self._settings.value("quality/bitrate", "8M")
        ms = self._settings.value("quality/maxsize", "0")
        fp = self._settings.value("quality/fps", "30")
        en = self._settings.value("quality/encoder", "Auto")
        idx = self.q_bitrate.findText(br)
        if idx >= 0: self.q_bitrate.setCurrentIndex(idx)
        idx = self.q_maxsize.findText(ms)
        if idx >= 0: self.q_maxsize.setCurrentIndex(idx)
        idx = self.q_fps.findText(fp)
        if idx >= 0: self.q_fps.setCurrentIndex(idx)
        idx = self.q_encoder.findText(en)
        if idx >= 0: self.q_encoder.setCurrentIndex(idx)

    def _save_custom_values(self):
        self._settings.setValue("quality/bitrate", self.q_bitrate.currentText())
        self._settings.setValue("quality/maxsize", self.q_maxsize.currentText())
        self._settings.setValue("quality/fps", self.q_fps.currentText())
        self._settings.setValue("quality/encoder", self.q_encoder.currentText())

    def _populate_quality_combo(self):
        self.quality_combo.blockSignals(True)
        self.quality_combo.clear()
        for name in ["ultra", "best", "medium", "low"]:
            self.quality_combo.addItem(name)
        saved = sorted(self._quality_presets.keys())
        for name in saved:
            self.quality_combo.addItem(name)
        self.quality_combo.addItem("Custom")
        idx = self.quality_combo.findText(self._last_quality)
        if idx >= 0:
            self.quality_combo.setCurrentIndex(idx)
        self.quality_combo.blockSignals(False)
        self._update_custom_panel_visibility()

    def _on_quality_changed(self, text):
        if not text:
            return
        self._last_quality = text
        self._settings.setValue("quality/last", text)
        is_builtin = text in ad.QUALITY_PRESETS
        is_saved = text in self._quality_presets
        self.custom_panel.setVisible(not is_builtin or is_saved)
        self.save_q_btn.setVisible(text == "Custom" or is_saved)
        self.save_q_btn.setText("Overwrite" if is_saved else "Save As\u2026")
        self.delete_q_btn.setVisible(is_saved)
        if is_saved:
            self._load_preset_into_panel(text)
        QTimer.singleShot(0, self._resize_to_fit)

    def _load_preset_into_panel(self, name):
        d = self._quality_presets.get(name)
        if not d:
            return
        idx = self.q_bitrate.findText(str(d.get("bit_rate", "8M")))
        if idx >= 0: self.q_bitrate.setCurrentIndex(idx)
        idx = self.q_maxsize.findText(str(d.get("max_size", "0")))
        if idx >= 0: self.q_maxsize.setCurrentIndex(idx)
        idx = self.q_fps.findText(str(d.get("max_fps", "30")))
        if idx >= 0: self.q_fps.setCurrentIndex(idx)
        idx = self.q_encoder.findText(d.get("encoder", "Auto"))
        if idx >= 0: self.q_encoder.setCurrentIndex(idx)

    def _update_custom_panel_visibility(self):
        text = self.quality_combo.currentText()
        is_builtin = text in ad.QUALITY_PRESETS
        is_saved = text in self._quality_presets
        self.custom_panel.setVisible(not is_builtin or is_saved)

    def _save_quality_preset(self):
        text = self.quality_combo.currentText()
        if text == "Custom":
            name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:")
            if not ok or not name.strip():
                return
            name = name.strip()
            d = {
                "bit_rate": self.q_bitrate.currentText(),
                "max_size": int(self.q_maxsize.currentText()),
                "max_fps": int(self.q_fps.currentText()),
                "encoder": self.q_encoder.currentText(),
            }
            self._quality_presets[name] = d
            self._settings.setValue("quality/saved", json.dumps(self._quality_presets))
            self._populate_quality_combo()
            self.quality_combo.setCurrentText(name)
        elif text in self._quality_presets:
            if text in ad.QUALITY_PRESETS:
                return  # can't overwrite built-in
            self._quality_presets[text] = {
                "bit_rate": self.q_bitrate.currentText(),
                "max_size": int(self.q_maxsize.currentText()),
                "max_fps": int(self.q_fps.currentText()),
                "encoder": self.q_encoder.currentText(),
            }
            self._settings.setValue("quality/saved", json.dumps(self._quality_presets))

    def _delete_quality_preset(self):
        text = self.quality_combo.currentText()
        if text in self._quality_presets and text not in ad.QUALITY_PRESETS:
            del self._quality_presets[text]
            self._settings.setValue("quality/saved", json.dumps(self._quality_presets))
            self._populate_quality_combo()

    def _get_current_quality(self):
        text = self.quality_combo.currentText()
        if text == "Custom":
            self._save_custom_values()
            return {
                "bit_rate": self.q_bitrate.currentText(),
                "max_size": int(self.q_maxsize.currentText()),
                "max_fps": int(self.q_fps.currentText()),
                "encoder": self.q_encoder.currentText(),
            }
        if text in self._quality_presets:
            return dict(self._quality_presets[text])
        if text in ad.QUALITY_PRESETS:
            return dict(ad.QUALITY_PRESETS[text])
        return None

    # ── iOS Quality ──────────────────────────────────────

    def _load_ios_quality_settings(self):
        self._ios_last_quality = self._settings.value("ios/quality/last", "medium")
        raw = self._settings.value("ios/quality/saved", "{}")
        if isinstance(raw, str):
            try:
                self._ios_quality_presets = json.loads(raw)
            except Exception:
                self._ios_quality_presets = {}
        self._populate_ios_quality_combo()
        self._restore_ios_custom_values()

    def _restore_ios_custom_values(self):
        res = self._settings.value("ios/quality/resolution", "1280x720@30")
        fps = self._settings.value("ios/quality/fps", "30")
        h265 = self._settings.value("ios/quality/h265", "No")
        idx = self.ios_q_res.findText(res)
        if idx >= 0: self.ios_q_res.setCurrentIndex(idx)
        idx = self.ios_q_fps.findText(fps)
        if idx >= 0: self.ios_q_fps.setCurrentIndex(idx)
        idx = self.ios_q_h265.findText(h265)
        if idx >= 0: self.ios_q_h265.setCurrentIndex(idx)

    def _save_ios_custom_values(self):
        self._settings.setValue("ios/quality/resolution", self.ios_q_res.currentText())
        self._settings.setValue("ios/quality/fps", self.ios_q_fps.currentText())
        self._settings.setValue("ios/quality/h265", self.ios_q_h265.currentText())

    def _populate_ios_quality_combo(self):
        self.ios_quality_combo.blockSignals(True)
        self.ios_quality_combo.clear()
        for name in ios_module.IOS_QUALITY_PRESETS:
            self.ios_quality_combo.addItem(name)
        saved = sorted(self._ios_quality_presets.keys())
        for name in saved:
            self.ios_quality_combo.addItem(name)
        self.ios_quality_combo.addItem("Custom")
        idx = self.ios_quality_combo.findText(self._ios_last_quality)
        if idx >= 0:
            self.ios_quality_combo.setCurrentIndex(idx)
        self.ios_quality_combo.blockSignals(False)
        self._update_ios_custom_panel_visibility()

    def _on_ios_quality_changed(self, text):
        if not text:
            return
        self._ios_last_quality = text
        self._settings.setValue("ios/quality/last", text)
        is_builtin = text in ios_module.IOS_QUALITY_PRESETS
        is_saved = text in self._ios_quality_presets
        self.ios_custom_panel.setVisible(not is_builtin or is_saved)
        self.ios_save_q_btn.setVisible(text == "Custom" or is_saved)
        self.ios_save_q_btn.setText("Overwrite" if is_saved else "Save As\u2026")
        self.ios_delete_q_btn.setVisible(is_saved)
        if is_saved:
            self._load_ios_preset_into_panel(text)
        QTimer.singleShot(0, self._resize_to_fit)
        if self.airplay.running:
            quality = self._get_current_ios_quality()
            self._cleanup_ios_control_bar()
            try:
                self.airplay.restart(quality)
                self._ios_retry_find_and_attach()
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def _load_ios_preset_into_panel(self, name):
        d = self._ios_quality_presets.get(name)
        if not d:
            return
        idx = self.ios_q_res.findText(str(d.get("resolution", "1280x720@30")))
        if idx >= 0: self.ios_q_res.setCurrentIndex(idx)
        idx = self.ios_q_fps.findText(str(d.get("fps", "30")))
        if idx >= 0: self.ios_q_fps.setCurrentIndex(idx)
        idx = self.ios_q_h265.findText("Yes" if d.get("h265") else "No")
        if idx >= 0: self.ios_q_h265.setCurrentIndex(idx)

    def _update_ios_custom_panel_visibility(self):
        text = self.ios_quality_combo.currentText()
        is_builtin = text in ios_module.IOS_QUALITY_PRESETS
        is_saved = text in self._ios_quality_presets
        self.ios_custom_panel.setVisible(not is_builtin or is_saved)

    def _save_ios_quality_preset(self):
        text = self.ios_quality_combo.currentText()
        if text == "Custom":
            name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:")
            if not ok or not name.strip():
                return
            name = name.strip()
            d = {
                "resolution": self.ios_q_res.currentText(),
                "fps": int(self.ios_q_fps.currentText()),
                "h265": self.ios_q_h265.currentText() == "Yes",
            }
            self._ios_quality_presets[name] = d
            self._settings.setValue("ios/quality/saved", json.dumps(self._ios_quality_presets))
            self._populate_ios_quality_combo()
            self.ios_quality_combo.setCurrentText(name)
        elif text in self._ios_quality_presets:
            if text in ios_module.IOS_QUALITY_PRESETS:
                return
            self._ios_quality_presets[text] = {
                "resolution": self.ios_q_res.currentText(),
                "fps": int(self.ios_q_fps.currentText()),
                "h265": self.ios_q_h265.currentText() == "Yes",
            }
            self._settings.setValue("ios/quality/saved", json.dumps(self._ios_quality_presets))

    def _delete_ios_quality_preset(self):
        text = self.ios_quality_combo.currentText()
        if text in self._ios_quality_presets and text not in ios_module.IOS_QUALITY_PRESETS:
            del self._ios_quality_presets[text]
            self._settings.setValue("ios/quality/saved", json.dumps(self._ios_quality_presets))
            self._populate_ios_quality_combo()

    def _get_current_ios_quality(self):
        text = self.ios_quality_combo.currentText()
        if text == "Custom":
            self._save_ios_custom_values()
            return {
                "resolution": self.ios_q_res.currentText(),
                "fps": int(self.ios_q_fps.currentText()),
                "h265": self.ios_q_h265.currentText() == "Yes",
            }
        if text in self._ios_quality_presets:
            return dict(self._ios_quality_presets[text])
        if text in ios_module.IOS_QUALITY_PRESETS:
            return dict(ios_module.IOS_QUALITY_PRESETS[text])
        return None

    def _get_ios_control_quality_options(self):
        items = []
        for name in ios_module.IOS_QUALITY_PRESETS:
            items.append(name)
        saved = sorted(self._ios_quality_presets.keys())
        items.extend(saved)
        return items

    def _open_pair_dialog(self):
        dlg = PairDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._scan_network()

    def _manual_connect(self):
        addr = self.manual_ip_input.text().strip()
        if not addr:
            QMessageBox.warning(self, "Error", "Enter IP:port (e.g. 192.168.1.10:5555)")
            return
        if ":" not in addr:
            addr = f"{addr}:5555"
        ip, port = addr.rsplit(":", 1)
        serial = f"{ip}:{port}"
        if serial in {d["serial"] for d in self.android_devices}:
            self.android_status.setText(f"Already connected: {serial}")
            return
        try:
            dev = ad.connect_device(ip, int(port))
            self.android_devices.append(dev)
            self.android_list.addItem(f"{dev['name']} ({dev['ip']})")
            self.android_status.setText(f"Connected: {dev['name']}")
        except Exception as e:
            QMessageBox.critical(self, "Connection Error", str(e))

    def _mirror_android(self):
        idx = self.android_list.currentRow()
        if idx < 0 or idx >= len(self.android_devices):
            return
        dev = self.android_devices[idx]
        serial = dev["serial"]
        name = dev.get("name", serial)
        quality = self._get_current_quality()
        try:
            ad.mirror_device(serial, quality)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            return
        self._retry_find_and_attach(serial, name, quality_name=self._last_quality)

    def _retry_find_and_attach(self, serial, name, retries=30, quality_name=None):
        self.android_status.setText(f"Starting mirror for {name}...")
        screen = self.screen()
        if not screen:
            return
        sg = screen.geometry()

        def attempt(count=0):
            if count >= retries:
                self.android_status.setText(f"Mirror started, but could not attach controls to {name}")
                return
            hwnd = ad.find_mirror_window(name)
            if hwnd is None:
                pid = ad.get_mirror_pid(serial)
                if pid:
                    hwnd = ad.find_mirror_window_by_pid(pid)
            if hwnd is not None:
                ad.move_hwnd_to_screen_center(hwnd, sg.x(), sg.y(), sg.width(), sg.height())
                quality_options = self._get_control_quality_options()
                cw = MirrorControlWindow(name, serial, media_dir=MEDIA_DIR,
                                         quality_options=quality_options,
                                         current_quality=quality_name)
                cw.set_hwnd(hwnd)
                cw.stop_requested.connect(self._stop_android_for)
                cw.aot_changed.connect(self._on_ctrl_aot_changed)
                cw.status_message.connect(self._on_ctrl_status_message)
                cw.quality_changed.connect(self._on_control_quality_changed)
                cw.show()
                self._control_bars[serial] = cw
                self.android_status.setText(f"Mirroring {name}")
            else:
                QTimer.singleShot(300, lambda c=count + 1: attempt(c))

        QTimer.singleShot(100, attempt)

    def _get_control_quality_options(self):
        items = []
        for name in ["ultra", "best", "medium", "low"]:
            items.append(name)
        saved = sorted(self._quality_presets.keys())
        items.extend(saved)
        return items

    def _on_control_quality_changed(self, serial, quality_name):
        dev = None
        for d in self.android_devices:
            if d["serial"] == serial:
                dev = d
                break
        if not dev:
            return
        name = dev.get("name", serial)
        cw = self._control_bars.get(serial)
        if cw:
            cw.cleanup()
            cw.deleteLater()
            self._control_bars.pop(serial, None)
        try:
            ad.stop_mirror(serial)
        except Exception:
            pass
        if quality_name in self._quality_presets:
            quality = dict(self._quality_presets[quality_name])
        elif quality_name in ad.QUALITY_PRESETS:
            quality = dict(ad.QUALITY_PRESETS[quality_name])
        else:
            quality = None
        try:
            ad.mirror_device(serial, quality)
        except Exception:
            return
        self._retry_find_and_attach(serial, name, quality_name=quality_name)

    def _on_ctrl_aot_changed(self, serial, enabled):
        for s, cw in self._control_bars.items():
            if s != serial:
                cw.set_aot(enabled)

    def _on_ctrl_status_message(self, serial, message):
        self.android_status.setText(message)

    def _stop_android_for(self, serial):
        try:
            ad.stop_mirror(serial)
        except Exception:
            pass
        self._cleanup_control_bar(serial)
        self._update_mirror_buttons()

    def _cleanup_control_bar(self, serial):
        bar = self._control_bars.pop(serial, None)
        if bar is not None:
            bar.cleanup()
            bar.deleteLater()

    def _stop_android(self):
        idx = self.android_list.currentRow()
        if idx < 0 or idx >= len(self.android_devices):
            return
        dev = self.android_devices[idx]
        try:
            ad.stop_mirror(dev["serial"])
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
        self._cleanup_control_bar(dev["serial"])

    def _update_mirror_buttons(self):
        idx = self.android_list.currentRow()
        if idx >= 0 and idx < len(self.android_devices):
            serial = self.android_devices[idx]["serial"]
            if ad.is_mirroring(serial):
                self.mirror_android_btn.setText("Mirroring...")
                self.mirror_android_btn.setEnabled(False)
                self.stop_android_btn.setEnabled(True)
            else:
                self.mirror_android_btn.setText("Start Mirror")
                self.mirror_android_btn.setEnabled(True)
                self.stop_android_btn.setEnabled(False)

    def _airplay_start(self):
        try:
            quality = self._get_current_ios_quality()
            self.airplay.start(quality)
            self.airplay_status.setText("Running")
            self.airplay_status.setStyleSheet("color: green; font-weight: bold;")
            self.airplay_start_btn.setEnabled(False)
            self.airplay_stop_btn.setEnabled(True)
            self._ios_retry_find_and_attach()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _ios_retry_find_and_attach(self, retries=45):
        self.airplay_status.setText("Waiting for iPhone to connect...")
        screen = self.screen()
        if not screen:
            return
        sg = screen.geometry()

        def attempt(count=0):
            if count >= retries:
                self.airplay_status.setText("iPhone not connected. Try again from your iPhone.")
                return
            hwnd = ad.find_mirror_window_by_titles(["UxPlay", "uxplay"])
            if hwnd is None:
                pid = self.airplay.pid
                hwnd = ad.find_mirror_window_by_pid(pid) if pid else None
            if hwnd is None:
                QTimer.singleShot(300, lambda c=count + 1: attempt(c))
                return
            ad.move_hwnd_to_screen_center(hwnd, sg.x(), sg.y(), sg.width(), sg.height())
            quality_options = self._get_ios_control_quality_options()
            quality_name = self.ios_quality_combo.currentText()
            cw = MirrorControlWindow("iPhone", "ios", media_dir=MEDIA_DIR,
                                     quality_options=quality_options,
                                     current_quality=quality_name,
                                     platform="ios")
            cw.set_hwnd(hwnd)
            cw.stop_requested.connect(self._airplay_for)
            cw.aot_changed.connect(self._on_ctrl_aot_changed)
            cw.status_message.connect(self._on_ctrl_status_message)
            cw.quality_changed.connect(self._on_ios_control_quality_changed)
            cw.show()
            self._ios_control_bar = cw
            self.airplay_status.setText("Mirroring iPhone")

        QTimer.singleShot(100, attempt)

    def _airplay_for(self, _serial):
        self._cleanup_ios_control_bar()
        self._airplay_stop_internal()

    def _airplay_stop_internal(self):
        self.airplay.stop()
        self.airplay_status.setText("Stopped")
        self.airplay_status.setStyleSheet("color: gray; font-weight: bold;")
        self.airplay_start_btn.setEnabled(True)
        self.airplay_stop_btn.setEnabled(False)

    def _airplay_stop(self):
        self._cleanup_ios_control_bar()
        self._airplay_stop_internal()

    def _cleanup_ios_control_bar(self):
        bar = self._ios_control_bar
        if bar is not None:
            self._ios_control_bar = None
            bar.cleanup()
            bar.deleteLater()

    def _on_ios_control_quality_changed(self, serial, quality_name):
        if quality_name in ios_module.IOS_QUALITY_PRESETS:
            quality = dict(ios_module.IOS_QUALITY_PRESETS[quality_name])
        elif quality_name in self._ios_quality_presets:
            quality = dict(self._ios_quality_presets[quality_name])
        else:
            return
        self._settings.setValue("ios/quality/last", quality_name)
        self._cleanup_ios_control_bar()
        try:
            self.airplay.restart(quality)
        except Exception:
            return
        self.ios_quality_combo.blockSignals(True)
        self.ios_quality_combo.setCurrentText(quality_name)
        self.ios_quality_combo.blockSignals(False)
        self._ios_retry_find_and_attach()

    def _resize_to_fit(self):
        try:
            self.resize(self.width(), self.minimumSizeHint().height())
        except Exception:
            pass

    def _restore_geometry(self):
        try:
            geom = self._settings.value("geometry")
            if geom is not None:
                self.restoreGeometry(geom)
            within = False
            screens = QGuiApplication.screens()
            if not screens:
                return
            cursor_pos = screens[0].geometry().center()
            for screen in screens:
                if screen.geometry().intersects(self.geometry()):
                    within = True
                if screen.geometry().contains(QGuiApplication.cursor().pos()):
                    cursor_pos = screen.geometry().center()
            if not within:
                self.move(cursor_pos.x() - self.width() // 2, cursor_pos.y() - self.height() // 2)
        except Exception:
            pass  # geometry restore is best-effort

    def closeEvent(self, event):
        self._settings.setValue("geometry", self.saveGeometry())
        self._save_favorites()
        self._settings.setValue("quality/last", self._last_quality)
        self._settings.setValue("quality/saved", json.dumps(self._quality_presets))
        self._save_custom_values()
        self._settings.setValue("ios/quality/last", self._ios_last_quality)
        self._settings.setValue("ios/quality/saved", json.dumps(self._ios_quality_presets))
        self._save_ios_custom_values()
        self._cleanup_ios_control_bar()
        for serial in list(self._control_bars.keys()):
            self._cleanup_control_bar(serial)
        try:
            self.airplay.stop()
        except Exception:
            pass
        for dev in self.android_devices:
            try:
                ad.stop_mirror(dev["serial"])
            except Exception:
                pass
        try:
            ad.adb_kill_server()
        except Exception:
            pass
        event.accept()


def main():
    try:
        os.environ["PATH"] = TOOLS_DIR + os.pathsep + os.environ.get("PATH", "")
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        w = MainWindow()
        w.show()
        return app.exec()
    except Exception as e:
        import traceback
        log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "error.log")
        with open(log_path, "w") as f:
            traceback.print_exc(file=f)
        raise
