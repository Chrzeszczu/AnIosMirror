import subprocess
from src.downloader import get_tool_path


IOS_QUALITY_PRESETS = {
    "high":   {"resolution": "1920x1080@60", "fps": 60, "h265": False},
    "medium": {"resolution": "1280x720@30",  "fps": 30, "h265": False},
    "low":    {"resolution": "854x480@24",   "fps": 24, "h265": False},
}


class AirPlayReceiver:
    def __init__(self):
        self._process = None

    @property
    def running(self):
        return self._process is not None and self._process.poll() is None

    @property
    def pid(self):
        if self._process and self._process.poll() is None:
            return self._process.pid
        return None

    def start(self, quality=None):
        if self.running:
            return
        uxplay = get_tool_path("uxplay")
        if not uxplay:
            raise RuntimeError("UxPlay not found. Download tools first.")
        args = [uxplay, "-n", "AnIosMirror"]
        if quality:
            res = quality.get("resolution")
            if res:
                args.extend(["-s", res])
            fps = quality.get("fps")
            if fps:
                args.extend(["-fps", str(fps)])
            if quality.get("h265"):
                args.append("-h265")
        self._process = subprocess.Popen(
            args,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    def stop(self):
        if self._process and self._process.poll() is None:
            self._process.kill()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            self._process = None

    def restart(self, quality=None):
        self.stop()
        self.start(quality)

    def get_status_text(self):
        if self.running:
            return "Running"
        return "Stopped"
