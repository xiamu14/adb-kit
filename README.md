# ADB QR Code Pairing & Connect

Android 11+ wireless debugging tool with QR code pairing and auto-connect support.

## Features

- **Pair Only** (default): Scan QR code to pair device
- **Pair and Connect**: Scan QR code to pair, then auto-connect with custom port
- **Connect Only**: Skip pairing, just scan QR to get IP and connect

## Usage

```bash
uv run main.py
```

Scans QR code and pairs the device, then auto-connects.

## Steps

1. Run the script with desired mode
2. On your Android device:
   - Go to **Developer options** � **Wireless debugging** � **Pair device with QR code**
3. Scan the QR code displayed in the browser or terminal
4. If using pair-connect or connect mode, enter the connection port in the browser page
5. Press Enter to exit

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
$ uv run main.py
[QR Code opened in browser]
Scan QR code to pair and connect.
[Developer options]-[Wireless debugging]-[Pair device with QR code]

Service debug added.
adb pair 192.168.1.100:37891 123456

Pair successful!
Enter the connect port in the browser page.
Executing: adb connect 192.168.1.100:5555
connected to 192.168.1.100:5555
```
