from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout, QMessageBox
from src.backends import android
from src.backends.android import get_local_subnet


class PairDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pair Android Device (QR Code)")
        self.setFixedWidth(460)
        layout = QVBoxLayout(self)

        _, my_ip = get_local_subnet()

        layout.addWidget(QLabel("Android 11+ Wireless Debugging pairing"))
        layout.addWidget(QLabel(
            "On your phone: Developer options \u2192 Wireless debugging \u2192\n"
            "Pair device with QR code \u2192 enter code, port, and computer IP"
        ))
        layout.addWidget(QLabel(f"Computer IP (enter on your phone): {my_ip}"))

        self.ip_input = QLineEdit()
        self.ip_input.setPlaceholderText("Computer IP (auto-detected)")
        self.ip_input.setText(my_ip)
        layout.addWidget(self.ip_input)

        self.port_input = QLineEdit()
        self.port_input.setPlaceholderText("Port from QR (e.g. 37153)")
        layout.addWidget(self.port_input)

        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("Code from QR (e.g. 123456)")
        layout.addWidget(self.code_input)

        btn_row = QHBoxLayout()
        self.pair_btn = QPushButton("Pair")
        self.pair_btn.clicked.connect(self._pair)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.pair_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        layout.addWidget(QLabel(
            "If Wireless Debugging is blocked by vendor:\n"
            "1. Connect USB, enable USB Debugging\n"
            "2. Run: .\\tools\\adb.exe tcpip 5555\n"
            "3. Disconnect USB, enter the phone IP manually in the main window"
        ))

    def _pair(self):
        code = self.code_input.text().strip()
        port = self.port_input.text().strip()
        ip = self.ip_input.text().strip() or None
        if not code or not port:
            QMessageBox.warning(self, "Error", "Enter both code and port")
            return
        try:
            android.pair_device(code, port, ip)
            QMessageBox.information(self, "Success", "Device paired and connected!")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
