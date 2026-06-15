# AnIosMirror

**AnIosMirror** is a Windows GUI tool that mirrors Android and iOS device screens wirelessly.

- **Android** – powered by [scrcpy](https://github.com/Genymobile/scrcpy) over ADB (Wi-Fi / USB)
- **iOS** – powered by [UxPlay](https://github.com/FDH2/UxPlay) via AirPlay (requires Bonjour/mDNS)

All external binaries are downloaded automatically on first launch – no manual setup required.

---

## Features

- **Wireless Android mirroring** – scan local network, enter IP manually, or pair via QR code (Android 11+)
- **iOS AirPlay mirroring** – works with any AirPlay-compatible iOS device
- **Always-on-top** toggle for mirror windows
- **One-click install** – double-click `install.bat` and you're ready
- **Portable** – no admin rights needed, everything stays in the project folder

---

## Requirements

- **OS**: Windows 10 / 11 (64-bit)
- **Python**: 3.10 or later ([python.org](https://www.python.org/downloads/))
- **iOS only**: [Bonjour Print Services for Windows](https://support.apple.com/en-us/106397) (mDNS) – required exactly once for AirPlay discovery

---

## Quick Start

### 1. One-click installation

Double-click `install.bat`:

```
install.bat
├── Checks Python is installed
├── Installs dependencies (pip install -r requirements.txt)
└── Creates a desktop shortcut
```

Then double-click the **AnIosMirror** shortcut on your desktop.

### 2. Manual installation

```cmd
pip install -r requirements.txt
python main.py
```

---

## Usage

### Android

1. **Prepare the device**
   - Enable **Developer options** and **USB Debugging** on your Android phone
   - Connect via USB once and run: `.\tools\adb.exe tcpip 5555`
   - Disconnect the USB cable
2. **Connect in the app**
   - Click **Scan** to find devices on your network, or enter the IP manually
   - For Android 11+, use **Pair** to pair via QR code (Wireless Debugging)
3. **Mirror**: select the device and click **Mirror**

### iOS

1. Install [Bonjour Print Services for Windows](https://support.apple.com/en-us/106397) (one-time only)
2. Connect your iOS device to the same Wi-Fi network
3. Click **Start AirPlay Receiver** in the app
4. On your iPhone/iPad, open Control Center → Screen Mirroring → select **AnIosMirror**

---

## Project Structure

```
AnIosMirror/
├── main.py                 # Application entry point
├── install.bat             # One-click installer
├── requirements.txt        # Python dependencies
├── src/
│   ├── app.py              # Main GUI (PyQt6)
│   ├── downloader.py       # Auto-downloads ADB / scrcpy / UxPlay
│   ├── backends/
│   │   ├── android.py      # ADB connection, scanning, mirroring
│   │   └── ios.py          # AirPlay receiver (UxPlay)
│   └── widgets/
│       └── pair_dialog.py  # QR pairing dialog
└── tools/                  # Downloaded binaries (created at runtime)
```

---

## Troubleshooting

| Problem | Solution |
|---|---|
| **"adb.exe is not recognized"** | Delete `tools/` folder and restart the app – it will be re-downloaded |
| **Wireless Debugging is blocked** | See the Pair dialog for USB fallback instructions |
| **iOS device not found** | Install [Bonjour](https://support.apple.com/en-us/106397) and ensure both devices are on the same Wi-Fi |
| **scrcpy window is blank** | Ensure USB Debugging was enabled and `adb tcpip 5555` was run at least once over USB |
| **Python is not installed** | Download Python 3.10+ from [python.org](https://www.python.org/downloads/) – make sure to check **Add to PATH** |

---

## License

MIT License – see [LICENSE](LICENSE).

This project bundles third-party binaries ([scrcpy](https://github.com/Genymobile/scrcpy) – Apache 2.0, [UxPlay](https://github.com/FDH2/UxPlay) – GPL-3.0) downloaded at runtime.
