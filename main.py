#!/usr/bin/env python3

"""
Android 11+ Wireless Debugging Helper
Pair and connect devices for wireless debug on terminal

python-zeroconf: A pure python implementation of multicast DNS service discovery
https://github.com/jstasiak/python-zeroconf

qrcode: Pure python QR Code generator
https://github.com/lincolnloop/python-qrcode
"""

import subprocess
import qrcode
from zeroconf import ServiceBrowser, Zeroconf


# ANSI color codes
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RED = '\033[91m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


TYPE_PAIRING = "_adb-tls-pairing._tcp.local."
NAME = "debug"
PASS = "123456"
FORMAT_QR = "WIFI:T:ADB;S:%s;P:%s;;"

CMD_PAIR = "adb pair %s:%s %s"
CMD_CONNECT = "adb connect %s:%s"
CMD_DEVICES = "adb devices -l"
CMD_REVERSE = "adb -s %s reverse tcp:8081 tcp:8081"
CMD_RESTART = "adb kill-server && adb start-server"


class ADBListener:
    """Listener for ADB wireless debugging services"""

    def __init__(self, mode="pair-connect", zeroconf_instance=None):
        self.mode = mode  # "pair-connect" or "connect"
        self.device_ip = None
        self.zeroconf = zeroconf_instance
        self.done = False

    def remove_service(self, zeroconf, type, name):
        pass

    def update_service(self, zeroconf, type, name):
        pass

    def add_service(self, zeroconf, type, name):
        info = zeroconf.get_service_info(type, name)
        if not info:
            return

        # Get actual IP address from addresses list
        ip_address = None
        if info.addresses:
            import ipaddress
            # Convert bytes to IP address string
            ip_address = str(ipaddress.ip_address(info.addresses[0]))

        print(f"\n{Colors.BLUE}Device found: {info.server}{Colors.RESET}")
        if ip_address:
            print(f"{Colors.BLUE}IP Address: {ip_address}{Colors.RESET}")

        self.device_ip = ip_address or info.server

        if self.mode == "pair-connect":
            self.pair_then_connect(info, ip_address)
        elif self.mode == "connect":
            self.connect_only(info, ip_address)

    def pair_then_connect(self, info, ip_address):
        """Pair device and then prompt for connect"""
        import sys

        cmd = CMD_PAIR % (info.server, info.port, PASS)
        print(f"{Colors.YELLOW}Pairing...{Colors.RESET}\n")
        sys.stdout.flush()

        result = subprocess.run(cmd, shell=True)

        # Force flush to ensure all output is displayed
        sys.stdout.flush()
        sys.stderr.flush()

        if result.returncode == 0:
            print(f"\n{Colors.GREEN}✓ Paired successfully{Colors.RESET}")
            print(f"{Colors.BLUE}Ready to connect to: {ip_address or info.server}{Colors.RESET}\n")
            sys.stdout.flush()
            self.prompt_connect(ip_address or info.server)
        else:
            print(f"\n{Colors.RED}✗ Pairing failed{Colors.RESET}")

    def connect_only(self, info, ip_address):
        """Connect to already paired device (only IP available from QR scan)"""
        self.prompt_connect(ip_address or info.server)

    def prompt_connect(self, ip):
        """Prompt user for connect port and execute adb connect"""
        import sys
        import time

        try:
            # Small delay to ensure all output is flushed
            time.sleep(0.2)
            sys.stdout.flush()
            sys.stderr.flush()

            port = input(f"{Colors.BOLD}Enter connect port (default 5555): {Colors.RESET}").strip()
            if not port:
                port = "5555"

            print(f"\n{Colors.YELLOW}Connecting to {ip}:{port}...{Colors.RESET}\n")
            sys.stdout.flush()

            cmd = CMD_CONNECT % (ip, port)
            result = subprocess.run(cmd, shell=True)

            sys.stdout.flush()
            sys.stderr.flush()

            if result.returncode == 0:
                print(f"{Colors.GREEN}✓ Connected successfully{Colors.RESET}\n")
            else:
                print(f"{Colors.RED}✗ Connection failed{Colors.RESET}\n")

            # Mark as done and close zeroconf
            self.done = True
            if self.zeroconf:
                self.zeroconf.close()

        except KeyboardInterrupt:
            print(f"\n{Colors.RED}Cancelled{Colors.RESET}\n")
            self.done = True
            if self.zeroconf:
                self.zeroconf.close()


def display_qr_code(text):
    """Generate and display a QR code in the terminal."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=1,
        border=1
    )
    qr.add_data(text)
    qr.make(fit=True)

    qr.print_ascii(invert=True)


def get_connected_devices():
    """Get list of connected ADB devices."""
    result = subprocess.run("adb devices", shell=True, capture_output=True, text=True)
    devices = []
    for line in result.stdout.strip().split('\n')[1:]:
        if line.strip() and 'device' in line:
            device_id = line.split()[0]
            devices.append(device_id)
    return devices


def select_device(devices):
    """Let user select a device from the list."""
    if not devices:
        print(f"{Colors.RED}No connected devices found{Colors.RESET}")
        return None

    if len(devices) == 1:
        print(f"{Colors.GREEN}Using device: {devices[0]}{Colors.RESET}")
        return devices[0]

    print(f"\n{Colors.BOLD}Connected devices:{Colors.RESET}")
    for i, device in enumerate(devices, 1):
        print(f"  {Colors.BLUE}{i}{Colors.RESET}. {device}")

    try:
        choice = input(f"\n{Colors.BOLD}Select device (1-{len(devices)}): {Colors.RESET}").strip()
        idx = int(choice) - 1
        if 0 <= idx < len(devices):
            return devices[idx]
        else:
            print(f"{Colors.RED}Invalid selection{Colors.RESET}")
            return None
    except (ValueError, KeyboardInterrupt):
        print(f"\n{Colors.RED}Cancelled{Colors.RESET}")
        return None


def run_reverse():
    """Run adb reverse command for selected device."""
    print(f"\n{Colors.BOLD}=== ADB Reverse ==={Colors.RESET}\n")

    devices = get_connected_devices()
    device = select_device(devices)

    if not device:
        return

    cmd = CMD_REVERSE % device
    print(f"\n{Colors.YELLOW}Running: {cmd}{Colors.RESET}\n")

    result = subprocess.run(cmd, shell=True)

    if result.returncode == 0:
        print(f"{Colors.GREEN}✓ Reverse port mapping established{Colors.RESET}")
    else:
        print(f"{Colors.RED}✗ Reverse failed{Colors.RESET}")


def run_restart():
    """Restart ADB server."""
    print(f"\n{Colors.BOLD}=== ADB Restart ==={Colors.RESET}\n")
    print(f"{Colors.YELLOW}Running: {CMD_RESTART}{Colors.RESET}\n")

    result = subprocess.run(CMD_RESTART, shell=True)

    if result.returncode == 0:
        print(f"{Colors.GREEN}✓ ADB server restarted{Colors.RESET}")
    else:
        print(f"{Colors.RED}✗ Restart failed{Colors.RESET}")


def run_devices():
    """List connected devices."""
    print(f"\n{Colors.BOLD}=== Connected Devices ==={Colors.RESET}\n")
    subprocess.run(CMD_DEVICES, shell=True)


def main():
    import sys

    mode = "pair-connect"

    # Parse command line arguments
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg in ["-c", "--connect"]:
            mode = "connect"
        elif arg in ["-p", "--pair-connect"]:
            mode = "pair-connect"
        elif arg in ["-s", "--reverse"]:
            run_reverse()
            return
        elif arg in ["-r", "--restart"]:
            run_restart()
            return
        elif arg in ["-d", "--devices"]:
            run_devices()
            return
        elif arg in ["-h", "--help"]:
            print(f"\n{Colors.BOLD}ADB Wireless Debug Helper{Colors.RESET}")
            print("\nUsage: python main.py [OPTIONS]")
            print("\nOptions:")
            print(f"  {Colors.GREEN}-p, --pair-connect{Colors.RESET}  Scan QR to pair, then connect (default)")
            print(f"  {Colors.BLUE}-c, --connect{Colors.RESET}       Scan QR to get IP, then connect (for paired devices)")
            print(f"  {Colors.YELLOW}-s, --reverse{Colors.RESET}       Setup reverse port (tcp:8081) for selected device")
            print(f"  {Colors.YELLOW}-r, --restart{Colors.RESET}       Restart ADB server (kill-server && start-server)")
            print(f"  {Colors.GREEN}-d, --devices{Colors.RESET}       List connected devices")
            print(f"  {Colors.YELLOW}-h, --help{Colors.RESET}          Show this help message")
            return

    text = FORMAT_QR % (NAME, PASS)

    print(f"\n{Colors.BOLD}=== ADB Wireless Debug ==={Colors.RESET}\n")

    display_qr_code(text)

    if mode == "pair-connect":
        print(f"\n{Colors.GREEN}Mode: Pair & Connect{Colors.RESET}")
        print("1. Scan QR code to pair new device")
        print("2. Then enter port to connect\n")
        print(f"{Colors.YELLOW}Path: Developer options > Wireless debugging > Pair device with QR code{Colors.RESET}")
    else:
        print(f"\n{Colors.BLUE}Mode: Connect Only{Colors.RESET}")
        print("1. Scan QR code to detect device IP")
        print("2. Then enter port to connect\n")
        print(f"{Colors.YELLOW}Path: Developer options > Wireless debugging > Pair device with QR code{Colors.RESET}")

    zeroconf = Zeroconf()
    listener = ADBListener(mode=mode, zeroconf_instance=zeroconf)
    browser = ServiceBrowser(zeroconf, TYPE_PAIRING, listener)

    print(f"\n{Colors.BOLD}Waiting for device...{Colors.RESET}")
    print(f"{Colors.YELLOW}(Press Ctrl+C to exit){Colors.RESET}\n")

    try:
        # Keep running until listener marks as done
        while not listener.done:
            import time
            time.sleep(0.5)
    except KeyboardInterrupt:
        print(f"\n{Colors.RED}Cancelled{Colors.RESET}")
    finally:
        try:
            zeroconf.close()
        except:
            pass
        print(f"\n{Colors.BLUE}Connected devices:{Colors.RESET}")
        subprocess.run(CMD_DEVICES, shell=True)


if __name__ == '__main__':
    main()
