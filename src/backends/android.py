import subprocess
import socket
import concurrent.futures
from pathlib import Path
from src.downloader import get_tool_path


def _adb(*args):
    adb = get_tool_path("adb")
    if not adb:
        raise RuntimeError("ADB not found. Download tools first.")
    result = subprocess.run([adb, *args], capture_output=True, text=True, timeout=10)
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


_mirror_processes = {}


def mirror_device(serial, always_on_top=False):
    scrcpy = get_tool_path("scrcpy")
    if not scrcpy:
        raise RuntimeError("scrcpy not found. Download tools first.")
    if serial in _mirror_processes:
        proc = _mirror_processes[serial]
        if proc.poll() is None:
            return  # already mirroring
    args = [scrcpy, "-s", serial, "--no-audio"]
    if always_on_top:
        args.append("--always-on-top")
    proc = subprocess.Popen(
        args,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    _mirror_processes[serial] = proc


def stop_mirror(serial):
    if serial in _mirror_processes:
        proc = _mirror_processes[serial]
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        del _mirror_processes[serial]


def is_mirroring(serial):
    if serial in _mirror_processes:
        return _mirror_processes[serial].poll() is None
    return False


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
