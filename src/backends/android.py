import subprocess
import socket
import ctypes
from ctypes import wintypes
import concurrent.futures
from pathlib import Path
from src.downloader import get_tool_path


def _adb(*args):
    adb = get_tool_path("adb")
    if not adb:
        raise RuntimeError("ADB not found. Download tools first.")
    flags = subprocess.CREATE_NO_WINDOW
    result = subprocess.run([adb, *args], capture_output=True, text=True, timeout=10, creationflags=flags)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def get_all_subnets():
    subnets = []
    try:
        import psutil
        for iface, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                    parts = addr.address.split(".")
                    subnet = f"{parts[0]}.{parts[1]}.{parts[2]}."
                    subnets.append((subnet, addr.address, iface))
    except ImportError:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        except Exception:
            ip = "127.0.0.1"
        finally:
            s.close()
        parts = ip.split(".")
        subnets.append((f"{parts[0]}.{parts[1]}.{parts[2]}.", ip, "default"))
    return subnets


def get_local_subnet():
    subnets = get_all_subnets()
    if subnets:
        return subnets[0][0], subnets[0][1]
    return "192.168.1.", "127.0.0.1"


def _check_port(ip, port=5555, timeout=1):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex((ip, port))
        s.close()
        return result == 0
    except:
        return False


def scan_network():
    results = []
    subnets = get_all_subnets()
    local_ips = {s[1] for s in subnets}

    already = get_connected_devices()
    results.extend(already)

    def try_ip(ip):
        if ip in local_ips:
            return None
        if not _check_port(ip, 5555, 0.3):
            return None
        code, out, _ = _adb("connect", f"{ip}:5555")
        if code == 0 and "connected" in out.lower():
            code2, out2, _ = _adb("devices")
            for line in out2.split("\n")[1:]:
                if ip in line and "device" in line:
                    serial = line.split()[0]
                    name = _get_device_name(serial)
                    return {"ip": ip, "serial": serial, "name": name}
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=100) as ex:
        futures = []
        for prefix, _, _ in subnets:
            for i in range(1, 255):
                futures.append(ex.submit(try_ip, f"{prefix}{i}"))
        for f in concurrent.futures.as_completed(futures):
            r = f.result()
            if r:
                already_ips = {d["ip"] for d in results}
                if r["ip"] not in already_ips:
                    results.append(r)

    return results


def _get_device_name(serial):
    code, out, _ = _adb("-s", serial, "shell", "getprop", "ro.product.model")
    return out.strip() if code == 0 else serial


def connect_device(ip, port=5555):
    code, out, _ = _adb("connect", f"{ip}:{port}")
    if code != 0:
        raise RuntimeError(f"Failed to connect: {out}")
    serial = f"{ip}:{port}"
    name = _get_device_name(serial)
    return {"ip": ip, "serial": serial, "name": name}


def pair_device(code, port, host=None):
    if not host:
        _, my_ip = get_local_subnet()
        host = my_ip
    addr = f"{host}:{port}"
    rc, out, err = _adb("pair", addr, code)
    if rc != 0:
        raise RuntimeError(f"Pairing failed: {err or out}")
    return out


QUALITY_PRESETS = {
    "ultra":  {"bit_rate": "100M", "max_size": 0,    "max_fps": 90, "encoder": ""},
    "best":   {"bit_rate": "50M",  "max_size": 0,    "max_fps": 60, "encoder": ""},
    "medium": {"bit_rate": "8M",   "max_size": 1920, "max_fps": 30, "encoder": ""},
    "low":    {"bit_rate": "2M",   "max_size": 1024, "max_fps": 15, "encoder": ""},
}

_mirror_processes = {}


def build_quality_args(quality):
    """Convert a quality dict to scrcpy argument list (without the executable and serial)."""
    args = []
    if quality.get("bit_rate"):
        args.extend(["--video-bit-rate", quality["bit_rate"]])
    ms = quality.get("max_size", 0)
    if ms and ms != "0":
        args.extend(["--max-size", str(ms)])
    mf = quality.get("max_fps", 0)
    if mf and mf != "0":
        args.extend(["--max-fps", str(mf)])
    enc = quality.get("encoder", "")
    if enc and enc.lower() not in ("auto", ""):
        args.extend(["--video-codec", enc])
    return args


def _drain_pipe(pipe):
    if pipe:
        try:
            pipe.read()
        except Exception:
            pass


def mirror_device(serial, quality=None):
    scrcpy = get_tool_path("scrcpy")
    if not scrcpy:
        raise RuntimeError("scrcpy not found. Download tools first.")
    if serial in _mirror_processes:
        proc = _mirror_processes[serial]
        if proc.poll() is None:
            return  # already mirroring
    args = [scrcpy, "-s", serial, "--no-audio"]
    if quality:
        args.extend(build_quality_args(quality))
    proc = subprocess.Popen(
        args,
        creationflags=subprocess.CREATE_NO_WINDOW,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        proc.wait(timeout=0.5)
        _, err = proc.communicate()
        detail = err.decode("utf-8", errors="replace").strip() if err else ""
        msg = f"scrcpy exited immediately (code {proc.returncode})"
        if detail:
            msg += f": {detail}"
        raise RuntimeError(msg)
    except subprocess.TimeoutExpired:
        pass
    import threading
    threading.Thread(target=_drain_pipe, args=(proc.stdout,), daemon=True).start()
    threading.Thread(target=_drain_pipe, args=(proc.stderr,), daemon=True).start()
    _mirror_processes[serial] = proc


def stop_mirror(serial):
    if serial in _mirror_processes:
        proc = _mirror_processes[serial]
        if proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        del _mirror_processes[serial]


def is_mirroring(serial):
    if serial in _mirror_processes:
        return _mirror_processes[serial].poll() is None
    return False


def adb_kill_server():
    """Kill the ADB server process to free the port and allow tools/ folder cleanup."""
    adb = get_tool_path("adb")
    flags = subprocess.CREATE_NO_WINDOW
    if adb:
        try:
            subprocess.run([adb, "kill-server"], capture_output=True, timeout=2, creationflags=flags)
        except Exception:
            pass
    try:
        subprocess.run(["taskkill", "/f", "/im", "adb.exe"], capture_output=True, timeout=2, creationflags=flags)
    except Exception:
        pass


def set_window_always_on_top(title_substr, enabled):
    try:
        hwnd = find_mirror_window(title_substr)
        if hwnd is not None:
            set_window_always_on_top_by_hwnd(hwnd, enabled)
    except Exception:
        pass


def set_window_always_on_top_by_hwnd(hwnd, enabled):
    try:
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        user32 = ctypes.windll.user32
        user32.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.UINT,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL
        user32.SetWindowPos(
            wintypes.HWND(hwnd),
            wintypes.HWND(-1 if enabled else -2),
            0, 0, 0, 0,
            wintypes.UINT(SWP_NOSIZE | SWP_NOMOVE),
        )
    except Exception:
        pass


def get_connected_devices():
    code, out, _ = _adb("devices")
    if code != 0:
        return []
    devices = []
    for line in out.split("\n")[1:]:
        line = line.strip()
        if line and "device" in line and "offline" not in line:
            serial = line.split()[0]
            name = _get_device_name(serial)
            devices.append({"ip": serial, "serial": serial, "name": name})
    return devices


def get_mirror_pid(serial):
    if serial in _mirror_processes:
        return _mirror_processes[serial].pid
    return None


def find_mirror_window(title_substr):
    """Find first visible window whose title contains title_substr. Returns HWND or None."""
    try:
        hwnds = []
        def enum_cb(hwnd, _):
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd) + 1
            buf = ctypes.create_unicode_buffer(length)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length)
            if title_substr.lower() in buf.value.lower():
                if ctypes.windll.user32.IsWindowVisible(hwnd):
                    hwnds.append(hwnd)
            return True
        cb = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        ctypes.windll.user32.EnumWindows(cb(enum_cb), 0)
        if hwnds:
            return hwnds[0]
    except Exception:
        pass
    return None


def find_mirror_window_by_pid(pid):
    """Find first visible window owned by process pid. Returns HWND or None."""
    try:
        hwnds = []
        def enum_cb(hwnd, _):
            window_pid = wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
            if window_pid.value == pid and ctypes.windll.user32.IsWindowVisible(hwnd):
                hwnds.append(hwnd)
            return True
        cb = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        ctypes.windll.user32.EnumWindows(cb(enum_cb), 0)
        if hwnds:
            return hwnds[0]
    except Exception:
        pass
    return None


def enum_visible_windows():
    """Return list of (hwnd, title) for all visible windows (debug helper)."""
    results = []
    try:
        def enum_cb(hwnd, _):
            if ctypes.windll.user32.IsWindowVisible(hwnd):
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd) + 1
                buf = ctypes.create_unicode_buffer(length)
                ctypes.windll.user32.GetWindowTextW(hwnd, buf, length)
                results.append((hwnd, buf.value))
            return True
        cb = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        ctypes.windll.user32.EnumWindows(cb(enum_cb), 0)
    except Exception:
        pass
    return results


def capture_window_screenshot(hwnd, output_dir):
    """Capture a screenshot of any window by HWND. Saves as PNG.
    Returns (filepath, None) or (None, error_message)."""
    try:
        from datetime import datetime
        from pathlib import Path
        from PIL import ImageGrab
        now = datetime.now()
        date_str = now.strftime("%d-%m-%Y")
        time_str = now.strftime("%H-%M-%S")
        folder = Path(output_dir) / "screenshots" / date_str
        folder.mkdir(parents=True, exist_ok=True)
        filepath = folder / f"{time_str}_{date_str}.png"

        rect = wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None, "Cannot get window rect"
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w <= 0 or h <= 0:
            return None, "Window has no size"

        img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
        img.save(filepath, "PNG")
        return str(filepath), None
    except Exception as e:
        return None, str(e)


def move_hwnd_to_screen_center(hwnd, screen_x, screen_y, screen_w, screen_h):
    """Move a window to the center of the specified screen. Does NOT resize."""
    try:
        rect = wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        target_x = screen_x + (screen_w - w) // 2
        target_y = screen_y + (screen_h - h) // 2
        if target_x < screen_x:
            target_x = screen_x
        if target_y < screen_y:
            target_y = screen_y
        ctypes.windll.user32.SetWindowPos(hwnd, 0, target_x, target_y, 0, 0, 0x0004 | 0x0001)  # SWP_NOZORDER | SWP_NOSIZE
    except Exception:
        pass


def get_hwnd_rect(hwnd):
    """Get window position and size as dict with keys x, y, w, h. Returns None on failure."""
    try:
        rect = wintypes.RECT()
        if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return {
                "x": rect.left, "y": rect.top,
                "w": rect.right - rect.left, "h": rect.bottom - rect.top
            }
    except Exception:
        pass
    return None


def take_screenshot(serial, output_dir):
    """Take screenshot from device via ADB.
    Saves to output_dir/screenshots/DD-MM-YYYY/HH-MM-SS_DD-MM-YYYY.png.
    Returns (filepath, None) or (None, error_message).
    """
    from datetime import datetime
    now = datetime.now()
    date_str = now.strftime("%d-%m-%Y")
    time_str = now.strftime("%H-%M-%S")

    folder = Path(output_dir) / "screenshots" / date_str
    folder.mkdir(parents=True, exist_ok=True)

    filename = f"{time_str}_{date_str}.png"
    filepath = folder / filename

    adb = get_tool_path("adb")
    if not adb:
        return None, "ADB not found"

    result = subprocess.run(
        [adb, "-s", serial, "exec-out", "screencap", "-p"],
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode != 0:
        return None, result.stderr.strip() or "Screenshot failed"

    filepath.write_bytes(result.stdout)
    return str(filepath), None


_recording_processes = {}


def _pull_and_clean(serial, info):
    """Helper: wait for process, pull file, remove remote, return (path|None, error|None)."""
    proc = info["proc"]
    remote = info["remote"]
    local = info["local"]
    adb = get_tool_path("adb")

    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2)

    if adb:
        subprocess.run(
            [adb, "-s", serial, "pull", remote, local],
            capture_output=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        subprocess.run(
            [adb, "-s", serial, "shell", "rm", remote],
            capture_output=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    if Path(local).exists():
        return local, None
    return None, "File not found after pull"


def _stop_current(serial):
    """Send SIGINT to the current screenrecord process on device."""
    adb = get_tool_path("adb")
    if not adb:
        return
    result = subprocess.run(
        [adb, "-s", serial, "shell", "pgrep", "screenrecord"],
        capture_output=True, text=True, timeout=5,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode == 0 and result.stdout.strip():
        pid = result.stdout.strip().split("\n")[-1]
        subprocess.run(
            [adb, "-s", serial, "shell", "kill", "-2", pid],
            capture_output=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )


def _make_filename(output_dir, suffix=""):
    from datetime import datetime
    now = datetime.now()
    date_str = now.strftime("%d-%m-%Y")
    time_str = now.strftime("%H-%M-%S")
    folder = Path(output_dir) / "recordings" / date_str
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{time_str}_{date_str}{suffix}.mp4"
    return str(folder / filename), f"/sdcard/{filename}"


def start_recording(serial, output_dir):
    """Start screen recording segment.
    Returns (local_path, None) or (None, error_message).
    """
    local_path, remote_path = _make_filename(output_dir)
    adb = get_tool_path("adb")
    if not adb:
        return None, "ADB not found"

    proc = subprocess.Popen(
        [adb, "-s", serial, "shell", "screenrecord", "--verbose", remote_path],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    data = _recording_processes.setdefault(serial, {"segments": [], "current": None})
    data["current"] = {"proc": proc, "remote": remote_path, "local": local_path}
    return local_path, None


def pause_recording(serial):
    """Pause: stop current segment, pull and save it, return its path."""
    data = _recording_processes.get(serial)
    if not data or not data["current"]:
        return None, "Not recording"
    cur = data["current"]
    data["current"] = None
    _stop_current(serial)
    local, err = _pull_and_clean(serial, cur)
    if local:
        data["segments"].append(local)
    return local, err


def resume_recording(serial, output_dir):
    """Resume: start a new recording segment."""
    return start_recording(serial, output_dir)


def stop_recording(serial):
    """Stop all segments, return (file_info, error).
    file_info is a single path if no pauses, or a merged path, or a list of paths.
    """
    data = _recording_processes.get(serial)
    if not data:
        return None, "Not recording"
    del _recording_processes[serial]

    files = list(data["segments"])
    if data["current"]:
        _stop_current(serial)
        local, _ = _pull_and_clean(serial, data["current"])
        if local:
            files.append(local)

    if not files:
        return None, "No files recorded"
    if len(files) == 1:
        return files[0], None
    # Multiple segments → try merging
    merged, err = _merge_segments(files)
    if merged:
        return merged, None
    return files, f"Merging failed ({err}), {len(files)} segments saved"


def _merge_segments(segments):
    """Merge multiple MP4 segments into one via ffmpeg concat demuxer.
    Returns (merged_path, None) or (None, error).
    """
    ffmpeg = get_tool_path("ffmpeg")
    if not ffmpeg:
        return None, "ffmpeg not found"

    import tempfile, os
    try:
        list_fd, list_path = tempfile.mkstemp(suffix=".txt", prefix="concat_")
        with os.fdopen(list_fd, "w") as f:
            for seg in segments:
                f.write(f"file '{seg}'" + "\n")
        first = Path(segments[0])
        merged_path = str(first.parent / f"{first.stem}_merged{first.suffix}")
        result = subprocess.run(
            [ffmpeg, "-f", "concat", "-safe", "0", "-i", list_path,
             "-c", "copy", "-y", merged_path],
            capture_output=True, text=True, timeout=120,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            Path(merged_path).unlink(missing_ok=True)
            return None, result.stderr.strip()[:200]
        for seg in segments:
            Path(seg).unlink(missing_ok=True)
        return merged_path, None
    finally:
        try:
            Path(list_path).unlink(missing_ok=True)
        except Exception:
            pass


def is_recording(serial):
    data = _recording_processes.get(serial)
    return bool(data and data["current"])
