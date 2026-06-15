import subprocess
import signal
from pathlib import Path
from src.downloader import get_tool_path


class AirPlayReceiver:
    def __init__(self):
        self._process = None

    @property
    def running(self):
        return self._process is not None and self._process.poll() is None

    def start(self):
        if self.running:
            return
        uxplay = get_tool_path("uxplay")
        if not uxplay:
            raise RuntimeError("UxPlay not found. Download tools first.")
        self._process = subprocess.Popen(
            [uxplay, "-n", "AnIosMirror"],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    def stop(self):
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

    def get_status_text(self):
        if self.running:
            return "Running"
        return "Stopped"
