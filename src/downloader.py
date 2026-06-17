import os
import zipfile
import io
import requests
import platform
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
TOOLS_DIR.mkdir(exist_ok=True)

TOOLS = {
    "adb": {
        "url": "https://dl.google.com/android/repository/platform-tools-latest-windows.zip",
        "subdir": "platform-tools",
        "files": ["adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll"],
    },
    "scrcpy": {
        "url": "https://github.com/Genymobile/scrcpy/releases/download/v4.0/scrcpy-win64-v4.0.zip",
        "subdir": "scrcpy-win64-v4.0",
        "files": ["scrcpy.exe", "scrcpy-server"],
    },
    "uxplay": {
        "url": "https://github.com/leapbtw/uxplay-windows/releases/download/2.0.0.1736/uxplay-windows.zip",
        "subdir": None,
        "files": ["uxplay-windows.exe", "mDNSResponder.exe"],
    },
}


def check_tools():
    missing = []
    for name, info in TOOLS.items():
        for f in info["files"]:
            if not (TOOLS_DIR / f).exists():
                missing.append(name)
                break
    return missing


def get_tool_path(name):
    info = TOOLS.get(name)
    if not info:
        return None
    for f in info["files"]:
        p = TOOLS_DIR / f
        if p.exists():
            return str(p)
    return None


def download_tools(progress_callback=None):
    missing = check_tools()
    if not missing:
    return True


def clean_tools():
    import shutil
    if not TOOLS_DIR.exists():
        return
    for f in TOOLS_DIR.iterdir():
        if f.is_dir():
            shutil.rmtree(f, ignore_errors=True)
        else:
            f.unlink(missing_ok=True)

    for name in missing:
        info = TOOLS[name]
        url = info["url"]
        if progress_callback:
            progress_callback(f"Downloading {name}...")

        resp = requests.get(url, stream=True, timeout=120)
        resp.raise_for_status()

        if url.endswith(".zip"):
            z = zipfile.ZipFile(io.BytesIO(resp.content))
            prefix = f"{info['subdir']}/" if info["subdir"] else ""
            for entry in z.namelist():
                if entry.endswith("/"):
                    continue
                fname = entry[len(prefix):] if entry.startswith(prefix) else entry
                if "/" in fname:
                    subdir = TOOLS_DIR / fname
                    subdir.parent.mkdir(parents=True, exist_ok=True)
                data = z.read(entry)
                (TOOLS_DIR / fname).write_bytes(data)
            z.close()
        else:
            (TOOLS_DIR / info["files"][0]).write_bytes(resp.content)

        if progress_callback:
            progress_callback(f"{name} ready.")

    return True
