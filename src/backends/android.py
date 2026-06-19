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


def get_process_children(parent_pid):
    """Return list of child PIDs for the given parent PID using Tool Help API."""
    children = []
    try:
        kernel32 = ctypes.windll.kernel32
        TH32CS_SNAPPROCESS = 0x00000002
        h = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if h == -1:
            return children
        try:
            PROCESSENTRY32 = 296
            entry = bytearray(PROCESSENTRY32)
            entry[0:4] = PROCESSENTRY32.to_bytes(4, "little")
            while kernel32.Process32Next(h, ctypes.byref(ctypes.c_char.from_buffer(entry))):
                th32ParentProcessID = int.from_bytes(entry[24:28], "little")
                th32ProcessID = int.from_bytes(entry[8:12], "little")
                if th32ParentProcessID == parent_pid:
                    children.append(th32ProcessID)
        finally:
            kernel32.CloseHandle(h)
    except Exception:
        pass
    return children


def find_mirror_window_by_pid(pid, include_children=True):
    """Find first visible window owned by process pid (and optionally its children).
    Returns HWND or None."""
    try:
        pids = {pid}
        if include_children:
            pids.update(get_process_children(pid))
        hwnds = []
        def enum_cb(hwnd, _):
            window_pid = wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
            if window_pid.value in pids and ctypes.windll.user32.IsWindowVisible(hwnd):
                hwnds.append(hwnd)
            return True
        cb = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        ctypes.windll.user32.EnumWindows(cb(enum_cb), 0)
        if hwnds:
            return hwnds[0]
    except Exception:
        pass
    return None


def find_mirror_window_by_titles(titles):
    """Find first visible window whose title contains any of the given substrings.
    Returns HWND or None."""
    try:
        hwnds = []
        lower = [t.lower() for t in titles]
        def enum_cb(hwnd, _):
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd) + 1
            buf = ctypes.create_unicode_buffer(length)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length)
            if any(s in buf.value.lower() for s in lower):
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


def _get_client_area_rect(hwnd):
    """Return (left, top, width, height) of window client area in screen coords."""
    rect = wintypes.RECT()
    if not ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    cw = rect.right
    ch = rect.bottom
    pt = wintypes.POINT(0, 0)
    if not ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(pt)):
        return None
    return pt.x, pt.y, cw, ch


def capture_window_screenshot(hwnd, output_dir):
    """Capture a screenshot of any window by HWND. Saves as PNG.
    Uses client area only (excludes window frame)."""
    try:
        from datetime import datetime
        from pathlib import Path
        from PIL import Image, ImageGrab
        now = datetime.now()
        date_str = now.strftime("%d-%m-%Y")
        time_str = now.strftime("%H-%M-%S")
        folder = Path(output_dir) / "screenshots" / date_str
        folder.mkdir(parents=True, exist_ok=True)
        filepath = folder / f"{time_str}_{date_str}.png"

        ca = _get_client_area_rect(hwnd)
        if not ca:
            return None, "Cannot get client rect"
        cx, cy, cw, ch = ca
        if cw <= 0 or ch <= 0:
            return None, "Window has no size"

        def _bitmap_to_pil(hbitmap, bw, bh):
            dc = ctypes.windll.user32.GetDC(0)
            bmp_info = ctypes.create_string_buffer(40)
            ctypes.windll.gdi32.GetDIBits(dc, hbitmap, 0, bh, None, bmp_info, 0)
            bpp = int.from_bytes(bmp_info[14:16], "little")
            stride = ((bw * bpp + 31) // 32) * 4
            pixels = ctypes.create_string_buffer(stride * abs(bh))
            ctypes.windll.gdi32.GetDIBits(dc, hbitmap, 0, bh,
                                           ctypes.byref(pixels), bmp_info, 0)
            ctypes.windll.user32.ReleaseDC(0, dc)
            img = Image.frombuffer("RGB", (bw, abs(bh)), pixels,
                                   "raw", "BGR", stride)
            if bh > 0:
                img = img.transpose(Image.FLIP_TOP_BOTTOM)
            return img

        # Method 1: PrintWindow (DirectX-aware via DWM, Win8+)
        for flag in (2, 0):
            try:
                desktop_dc = ctypes.windll.user32.GetDC(0)
                mem_dc = ctypes.windll.gdi32.CreateCompatibleDC(desktop_dc)
                hbitmap = ctypes.windll.gdi32.CreateCompatibleBitmap(desktop_dc, cw, ch)
                old = ctypes.windll.gdi32.SelectObject(mem_dc, hbitmap)
                ok = ctypes.windll.user32.PrintWindow(hwnd, mem_dc, flag)
                ctypes.windll.gdi32.SelectObject(mem_dc, old)
                ctypes.windll.gdi32.DeleteDC(mem_dc)
                ctypes.windll.user32.ReleaseDC(0, desktop_dc)
                if ok:
                    img = _bitmap_to_pil(hbitmap, cw, ch)
                    ctypes.windll.gdi32.DeleteObject(hbitmap)
                    img.save(str(filepath), "PNG")
                    return str(filepath), None
                ctypes.windll.gdi32.DeleteObject(hbitmap)
            except Exception:
                pass

        # Method 2: BitBlt from desktop DC (client area only)
        try:
            desktop_dc = ctypes.windll.user32.GetDC(0)
            mem_dc = ctypes.windll.gdi32.CreateCompatibleDC(desktop_dc)
            bitmap = ctypes.windll.gdi32.CreateCompatibleBitmap(desktop_dc, cw, ch)
            old = ctypes.windll.gdi32.SelectObject(mem_dc, bitmap)
            ctypes.windll.gdi32.BitBlt(mem_dc, 0, 0, cw, ch, desktop_dc,
                                        cx, cy, 0x00CC0020)
            ctypes.windll.gdi32.SelectObject(mem_dc, old)
            ctypes.windll.gdi32.DeleteDC(mem_dc)
            ctypes.windll.user32.ReleaseDC(0, desktop_dc)
            img = _bitmap_to_pil(bitmap, cw, ch)
            ctypes.windll.gdi32.DeleteObject(bitmap)
            img.save(str(filepath), "PNG")
            return str(filepath), None
        except Exception:
            pass

        # Method 3: PIL ImageGrab fallback (client area only)
        img = ImageGrab.grab(bbox=(cx, cy, cx + cw, cy + ch))
        img.save(str(filepath), "PNG")
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


# ── Window-based recording (iOS / general) ────────────────

_window_record_processes = {}

def _get_window_title(hwnd):
    try:
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd) + 1
        buf = ctypes.create_unicode_buffer(length)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length)
        return buf.value
    except Exception:
        return None


def start_window_recording(hwnd, output_dir):
    """Record a window via ffmpeg ddagrab (DXGI). Returns (filepath, None) or (None, error)."""
    ffmpeg = get_tool_path("ffmpeg")
    if not ffmpeg:
        return None, "ffmpeg not found"
    from datetime import datetime
    now = datetime.now()
    date_str = now.strftime("%d-%m-%Y")
    time_str = now.strftime("%H-%M-%S")
    folder = Path(output_dir) / "recordings" / date_str
    folder.mkdir(parents=True, exist_ok=True)
    filepath = folder / f"{time_str}_{date_str}.mp4"

    ca = _get_client_area_rect(hwnd)
    if not ca:
        return None, "Cannot get client rect"
    cx, cy, cw, ch = ca
    if cw <= 0 or ch <= 0:
        return None, "Window has no size"

    try:
        proc = subprocess.Popen(
            [ffmpeg, "-f", "dda", "-i", "0",
             "-filter:v", f"crop={cw}:{ch}:{cx}:{cy}",
             "-c:v", "libx264", "-preset", "ultrafast",
             "-pix_fmt", "yuv420p", "-y", str(filepath)],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        return None, "ddagrab not supported; try a newer ffmpeg build"
    _window_record_processes[hwnd] = {"proc": proc, "path": str(filepath)}
    return str(filepath), None


def stop_window_recording(hwnd):
    """Stop window recording. Returns (filepath, None) or (None, error)."""
    data = _window_record_processes.pop(hwnd, None)
    if not data:
        return None, "Not recording"
    proc = data["proc"]
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
    return data["path"], None


def is_window_recording(hwnd):
    return hwnd in _window_record_processes
