import sys
import os
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem, QGroupBox,
    QProgressBar, QMessageBox, QDialog, QLineEdit, QCheckBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer

from src.downloader import check_tools, download_tools, get_tool_path
from src.backends import android as ad
from src.backends.ios import AirPlayReceiver
from src.widgets.pair_dialog import PairDialog

TOOLS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tools")


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
        self.setFixedSize(520, 600)

        self.android_devices = []
        self.airplay = AirPlayReceiver()
        self._scan_worker = None

        self._build_ui()
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
        self.pair_btn = QPushButton("Pair with QR Code")
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
        android_layout.addLayout(manual_row)

        self.always_on_top_cb = QCheckBox("Always on Top")
        android_layout.addWidget(self.always_on_top_cb)

        btn_mirror_row = QHBoxLayout()
        self.mirror_android_btn = QPushButton("Mirror")
        self.mirror_android_btn.clicked.connect(self._mirror_android)
        self.mirror_android_btn.setEnabled(False)
        self.stop_android_btn = QPushButton("Stop Mirror")
        self.stop_android_btn.clicked.connect(self._stop_android)
        self.stop_android_btn.setEnabled(False)
        btn_mirror_row.addWidget(self.mirror_android_btn)
        btn_mirror_row.addWidget(self.stop_android_btn)
        android_layout.addLayout(btn_mirror_row)

        self.android_status = QLabel("Status: idle")
        android_layout.addWidget(self.android_status)
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

        ios_help = QLabel(
            "Na iPhonie: Control Center \u2192 Screen Mirroring \u2192 wybierz AnIosMirror"
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
        try:
            ad.mirror_device(dev["serial"], self.always_on_top_cb.isChecked())
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _stop_android(self):
        idx = self.android_list.currentRow()
        if idx < 0 or idx >= len(self.android_devices):
            return
        dev = self.android_devices[idx]
        try:
            ad.stop_mirror(dev["serial"])
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _update_mirror_buttons(self):
        idx = self.android_list.currentRow()
        if idx >= 0 and idx < len(self.android_devices):
            serial = self.android_devices[idx]["serial"]
            if ad.is_mirroring(serial):
                self.mirror_android_btn.setText("Mirror (active)")
                self.mirror_android_btn.setEnabled(False)
                self.stop_android_btn.setEnabled(True)
            else:
                self.mirror_android_btn.setText("Mirror")
                self.mirror_android_btn.setEnabled(True)
                self.stop_android_btn.setEnabled(False)

    def _airplay_start(self):
        try:
            self.airplay.start()
            self.airplay_status.setText("Running")
            self.airplay_status.setStyleSheet("color: green; font-weight: bold;")
            self.airplay_start_btn.setEnabled(False)
            self.airplay_stop_btn.setEnabled(True)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _airplay_stop(self):
        self.airplay.stop()
        self.airplay_status.setText("Stopped")
        self.airplay_status.setStyleSheet("color: gray; font-weight: bold;")
        self.airplay_start_btn.setEnabled(True)
        self.airplay_stop_btn.setEnabled(False)

    def closeEvent(self, event):
        self.airplay.stop()
        for dev in self.android_devices:
            ad.stop_mirror(dev["serial"])
        event.accept()


def main():
    os.environ["PATH"] = TOOLS_DIR + os.pathsep + os.environ.get("PATH", "")
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = MainWindow()
    w.show()
    return app.exec()
