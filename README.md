# ADB QR Code Pairing & Connect

Android 11+ wireless debugging tool with QR code pairing and auto-connect support.

## Features

- **Pair and Connect** (default): Scan QR code to pair, then auto-connect through mDNS
- **Connect Only**: Skip pairing and connect to the discovered wireless debugging service

## Usage

```bash
uv run ak wireless
```

Scans QR code and pairs the device, then auto-connects.

```bash
uv run ak restart
uv run ak -s -r 8081
uv run ak -s <device> -r 9091
```

## Steps

1. Run the script with desired mode
2. On your Android device:
   - Go to **Developer options** � **Wireless debugging** � **Pair device with QR code**
3. Scan the QR code displayed in the browser or terminal
4. Wait for the wireless debugging connection port to be auto-discovered
5. If auto-discovery does not appear, enter the connection port shown on the device in the browser page
6. Press Enter to exit

## Requirements

- Python 3.6+
- uv
- python-zeroconf
- qrcode

Install dependencies:
```bash
uv sync
```

## Example

```bash
$ uv run ak wireless
[QR Code opened in browser]
Scan QR code to pair and connect.
[Developer options]-[Wireless debugging]-[Pair device with QR code]

Service debug added.
adb pair 192.168.1.100:37891 123456

Pair successful!
Auto-discovered port 37123. Connecting...
Executing: adb connect 192.168.1.100:37123
connected to 192.168.1.100:37123
```
