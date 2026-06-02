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
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import escape
from io import BytesIO
from pathlib import Path
from queue import Empty, Queue
from urllib.parse import parse_qs

import qrcode
import qrcode.image.svg
from zeroconf import ServiceBrowser, Zeroconf


# ANSI color codes
class Colors:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    RED = "\033[91m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


TYPE_PAIRING = "_adb-tls-pairing._tcp.local."
TYPE_CONNECT = "_adb-tls-connect._tcp.local."
NAME = "debug"
PASS = "123456"
FORMAT_QR = "WIFI:T:ADB;S:%s;P:%s;;"

CMD_PAIR = "adb pair %s:%s %s"
CMD_CONNECT = "adb connect %s:%s"
CMD_DEVICES = "adb devices -l"
CMD_REVERSE = "adb -s %s reverse tcp:8081 tcp:8081"
CMD_RESTART = "adb kill-server && adb start-server"

PROJECT_DIR = Path(__file__).resolve().parent
QR_CACHE_DIR = PROJECT_DIR / ".cache"
QR_CACHE_TTL_SECONDS = 60
AUTO_CONNECT_WAIT_SECONDS = 8


class ADBListener:
    """Listener for ADB wireless debugging services"""

    def __init__(
        self,
        mode="pair-connect",
        zeroconf_instance=None,
        qr_code_path=None,
        qr_code_cleanup_timer=None,
        browser_session=None,
    ):
        self.mode = mode  # "pair-connect" or "connect"
        self.device_ip = None
        self.zeroconf = zeroconf_instance
        self.done = False
        self.qr_code_path = qr_code_path
        self.qr_code_cleanup_timer = qr_code_cleanup_timer
        self.browser_session = browser_session
        self.lock = threading.Lock()
        self.pairing_started = False
        self.paired = False
        self.connect_started = False
        self.pending_connect_service = None

    def remove_service(self, zeroconf, type, name):
        pass

    def update_service(self, zeroconf, type, name):
        pass

    def add_service(self, zeroconf, type, name):
        with self.lock:
            if self.done:
                return

        info = zeroconf.get_service_info(type, name)
        if not info:
            return

        ip_address = get_service_ip_address(info)

        print(f"\n{Colors.BLUE}Device found: {info.server}{Colors.RESET}")
        print(f"{Colors.BLUE}Service type: {type}{Colors.RESET}")
        if ip_address:
            print(f"{Colors.BLUE}IP Address: {ip_address}{Colors.RESET}")

        if type == TYPE_PAIRING:
            if self.mode != "pair-connect":
                return
            with self.lock:
                if self.pairing_started:
                    return
                self.pairing_started = True

            self.device_ip = ip_address or info.server
            if self.browser_session:
                self.browser_session.set_device_found(self.device_ip)

            self.pair_then_connect(info, ip_address)
        elif type == TYPE_CONNECT:
            self.connect_from_service(info, ip_address)

    def connect_from_service(self, info, ip_address):
        """Use the wireless debugging connect service when it is advertised."""
        ip = ip_address or info.server
        port = str(info.port)

        with self.lock:
            if self.connect_started:
                return
            if self.mode == "pair-connect" and not self.paired:
                self.pending_connect_service = (ip, port)
                return
            if self.mode == "connect":
                self.connect_started = True

        if self.mode == "connect":
            self.run_connect(ip, port)
            return

        if self.browser_session:
            self.browser_session.set_auto_connect_port(ip, port)
        else:
            with self.lock:
                if self.connect_started:
                    return
                self.connect_started = True
            self.run_connect(ip, port)

    def pair_then_connect(self, info, ip_address):
        """Pair device and then connect with browser-entered or discovered port."""
        import sys

        cmd = CMD_PAIR % (ip_address or info.server, info.port, PASS)
        print(f"{Colors.YELLOW}Pairing...{Colors.RESET}\n")
        if self.browser_session:
            self.browser_session.set_pairing()
        sys.stdout.flush()

        result = subprocess.run(cmd, shell=True)

        # Force flush to ensure all output is displayed
        sys.stdout.flush()
        sys.stderr.flush()

        if result.returncode == 0:
            print(f"\n{Colors.GREEN}✓ Paired successfully{Colors.RESET}")
            print(
                f"{Colors.BLUE}Ready to connect to: {ip_address or info.server}{Colors.RESET}\n"
            )
            sys.stdout.flush()

            with self.lock:
                self.paired = True
                pending_connect_service = self.pending_connect_service

            if pending_connect_service:
                pending_ip, pending_port = pending_connect_service
                if self.browser_session:
                    self.browser_session.set_auto_connect_port(
                        pending_ip, pending_port
                    )
                else:
                    self.run_connect(pending_ip, pending_port)
                    return

            self.prompt_connect(ip_address or info.server)
        else:
            print(f"\n{Colors.RED}✗ Pairing failed{Colors.RESET}")
            if self.browser_session:
                self.browser_session.set_error("Pairing failed")
            self.done = True
            if self.zeroconf:
                self.zeroconf.close()

    def connect_only(self, info, ip_address):
        """Connect to already paired device with browser-entered or discovered port."""
        self.prompt_connect(ip_address or info.server)

    def prompt_connect(self, ip):
        """Prompt user for connect port and execute adb connect."""
        import sys
        import time

        try:
            time.sleep(0.2)
            sys.stdout.flush()
            sys.stderr.flush()

            if self.browser_session:
                print(
                    f"{Colors.BOLD}Waiting for auto-discovered connect port. Browser input is fallback only.{Colors.RESET}"
                )
                self.browser_session.set_paired(ip)
                connect_ip, port = self.browser_session.wait_for_connect_target(
                    fallback_delay_seconds=AUTO_CONNECT_WAIT_SECONDS
                )
                ip = connect_ip or ip
            else:
                port = input(
                    f"{Colors.BOLD}Enter connect port (default 5555): {Colors.RESET}"
                ).strip()
            if not port:
                port = "5555"

            with self.lock:
                if self.connect_started:
                    return
                self.connect_started = True

            self.run_connect(ip, port)

        except KeyboardInterrupt:
            print(f"\n{Colors.RED}Cancelled{Colors.RESET}\n")
            if self.browser_session:
                self.browser_session.set_error("Cancelled")
            self.done = True
            if self.zeroconf:
                self.zeroconf.close()

    def run_connect(self, ip, port):
        """Execute adb connect with the discovered wireless debugging port."""
        import sys
        import time

        try:
            time.sleep(0.2)
            sys.stdout.flush()
            sys.stderr.flush()

            print(f"\n{Colors.YELLOW}Connecting to {ip}:{port}...{Colors.RESET}\n")
            if self.browser_session:
                self.browser_session.set_connecting(ip, port)
            sys.stdout.flush()

            cmd = CMD_CONNECT % (ip, port)
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

            if result.stdout:
                print(result.stdout, end="")
            if result.stderr:
                print(result.stderr, end="", file=sys.stderr)

            sys.stdout.flush()
            sys.stderr.flush()

            if result.returncode == 0 and is_adb_connect_success(
                result.stdout + result.stderr
            ):
                print(f"{Colors.GREEN}✓ Connected successfully{Colors.RESET}\n")
                if self.browser_session:
                    self.browser_session.set_connected()
                if self.qr_code_path:
                    if self.qr_code_cleanup_timer:
                        self.qr_code_cleanup_timer.cancel()
                    delete_qr_code_file(self.qr_code_path)
            else:
                print(f"{Colors.RED}✗ Connection failed{Colors.RESET}\n")
                if self.browser_session:
                    self.browser_session.set_error("Connection failed")

            # Mark as done and close zeroconf
            self.done = True
            if self.zeroconf:
                self.zeroconf.close()

        except KeyboardInterrupt:
            print(f"\n{Colors.RED}Cancelled{Colors.RESET}\n")
            if self.browser_session:
                self.browser_session.set_error("Cancelled")
            self.done = True
            if self.zeroconf:
                self.zeroconf.close()


def get_service_ip_address(info):
    """Return the first IP address advertised by a zeroconf service."""
    if not info.addresses:
        return None

    import ipaddress

    addresses = [ipaddress.ip_address(address) for address in info.addresses]
    for address in addresses:
        if address.version == 4:
            return str(address)
    return str(addresses[0])


def is_adb_connect_success(output):
    output = output.lower()
    return "connected to" in output or "already connected to" in output


def display_qr_code(text):
    """Generate and display a QR code in the terminal."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=1,
        border=1,
    )
    qr.add_data(text)
    qr.make(fit=True)

    qr.print_ascii(invert=True)


def delete_qr_code_file(path):
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def delete_file_later(path, delay_seconds=QR_CACHE_TTL_SECONDS):
    """Delete a generated file after a short delay."""

    def delete_file():
        delete_qr_code_file(path)

    timer = threading.Timer(delay_seconds, delete_file)
    timer.daemon = True
    timer.start()
    return timer


def build_qr_svg(text, box_size=12):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=box_size,
        border=4,
    )
    qr.add_data(text)
    qr.make(fit=True)

    image = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    svg_buffer = BytesIO()
    image.save(svg_buffer)
    return svg_buffer.getvalue().decode("utf-8")


class BrowserPairingSession:
    """Small local browser UI for QR display and connect-port entry."""

    def __init__(self, text):
        self.text = text
        self.qr_svg = build_qr_svg(text)
        self.connect_target_queue = Queue(maxsize=1)
        self.lock = threading.Lock()
        self.state = {
            "status": "waiting",
            "message": "Scan the QR code on your Android device.",
            "deviceIp": "",
            "canSubmit": False,
            "done": False,
            "error": "",
        }
        self.server = None
        self.thread = None

    def start(self):
        session = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def do_GET(self):
                if self.path.startswith("/state"):
                    self.send_json(session.snapshot())
                    return

                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(session.render_html().encode("utf-8"))

            def do_POST(self):
                if not self.path.startswith("/connect"):
                    self.send_error(404)
                    return

                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length).decode("utf-8")
                port = parse_qs(body).get("port", [""])[0].strip() or "5555"
                session.submit_port(port)
                self.send_json({"ok": True})

            def send_json(self, payload):
                import json

                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            name="adb-browser-session",
            daemon=True,
        )
        self.thread.start()
        return f"http://127.0.0.1:{self.server.server_port}/"

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def update(self, **changes):
        with self.lock:
            self.state.update(changes)

    def set_device_found(self, ip):
        self.update(
            status="device_found",
            message="Device found. Pairing now...",
            deviceIp=ip,
        )

    def set_pairing(self):
        self.update(status="pairing", message="Pairing with ADB...")

    def set_paired(self, ip):
        self.update(
            status="paired",
            message="Paired successfully. Waiting for wireless connection port...",
            deviceIp=ip,
            canSubmit=False,
        )

    def set_ready_to_connect(self, ip):
        self.update(
            status="ready",
            message="Device found. Waiting for wireless connection port...",
            deviceIp=ip,
            canSubmit=False,
        )

    def set_auto_connect_port(self, ip, port):
        self.submit_port(port, ip)
        self.update(
            status="auto_port_found",
            message=f"Auto-discovered port {port}. Connecting...",
            deviceIp=ip,
            canSubmit=False,
        )

    def set_connecting(self, ip, port):
        self.update(
            status="connecting",
            message=f"Connecting to {ip}:{port}...",
            canSubmit=False,
        )

    def set_connected(self):
        self.update(
            status="connected",
            message="Connected successfully. Closing this page...",
            canSubmit=False,
            done=True,
        )

    def set_error(self, message):
        self.update(status="error", message=message, error=message, canSubmit=False)

    def submit_port(self, port, ip=None):
        try:
            self.connect_target_queue.put_nowait((ip, port))
        except Exception:
            pass
        self.update(canSubmit=False, message="Port submitted. Connecting...")

    def wait_for_connect_target(self, fallback_delay_seconds=0):
        fallback_started = False
        deadline = None
        if fallback_delay_seconds:
            import time

            deadline = time.monotonic() + fallback_delay_seconds
        else:
            fallback_started = True
            self.update(canSubmit=True)

        while True:
            try:
                return self.connect_target_queue.get(timeout=0.5)
            except Empty:
                state = self.snapshot()
                if state.get("done") or state.get("error"):
                    raise KeyboardInterrupt
                if deadline and not fallback_started:
                    import time

                    if time.monotonic() >= deadline:
                        fallback_started = True
                        self.update(
                            message="Auto-discovery is still pending. Enter the port shown on the device if needed.",
                            canSubmit=True,
                        )

    def render_html(self):
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ADB Wireless Debug</title>
  <style>
    :root {{
      color-scheme: light dark;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    body {{
      background: #f5f7fb;
      color: #172033;
      margin: 0;
      min-height: 100vh;
    }}
    main {{
      align-items: center;
      display: grid;
      gap: 22px;
      grid-template-columns: minmax(280px, 520px) minmax(280px, 380px);
      justify-content: center;
      min-height: 100vh;
      padding: 32px;
    }}
    h1 {{
      font-size: 28px;
      font-weight: 700;
      margin: 0;
    }}
    .qr {{
      background: #ffffff;
      border: 1px solid #d9e0ec;
      border-radius: 8px;
      box-shadow: 0 18px 60px rgba(23, 32, 51, 0.16);
      padding: 24px;
    }}
    .qr svg {{
      display: block;
      height: min(70vw, 520px);
      width: min(70vw, 520px);
    }}
    .panel {{
      display: flex;
      flex-direction: column;
      gap: 14px;
    }}
    .status {{
      color: #506178;
      line-height: 1.45;
      min-height: 44px;
    }}
    code {{
      background: rgba(23, 32, 51, 0.08);
      border-radius: 6px;
      font-size: 14px;
      padding: 8px 10px;
      word-break: break-all;
    }}
    form {{
      display: flex;
      gap: 10px;
    }}
    input {{
      border: 1px solid #b9c4d4;
      border-radius: 8px;
      font: inherit;
      min-width: 0;
      padding: 10px 12px;
      width: 100%;
    }}
    button {{
      background: #1769e0;
      border: 0;
      border-radius: 8px;
      color: #ffffff;
      cursor: pointer;
      font: inherit;
      font-weight: 700;
      padding: 10px 16px;
    }}
    button:disabled,
    input:disabled {{
      cursor: not-allowed;
      opacity: 0.55;
    }}
    @media (max-width: 860px) {{
      main {{
        grid-template-columns: 1fr;
        min-height: auto;
      }}
      .qr svg {{
        height: min(82vw, 520px);
        width: min(82vw, 520px);
      }}
    }}
    @media (prefers-color-scheme: dark) {{
      body {{
        background: #101522;
        color: #eef3ff;
      }}
      .qr {{
        background: #ffffff;
        border-color: #2f3a4f;
      }}
      .status {{
        color: #b9c4d4;
      }}
      code {{
        background: rgba(238, 243, 255, 0.12);
      }}
      input {{
        background: #171e2d;
        border-color: #3a465c;
        color: #eef3ff;
      }}
    }}
  </style>
</head>
<body>
  <div id="toaster-root"></div>
  <main>
    <div class="qr">{self.qr_svg}</div>
    <section class="panel">
      <h1>ADB Wireless Debug</h1>
      <div class="status" id="status">Scan the QR code on your Android device.</div>
      <form id="connect-form">
        <input id="port" name="port" inputmode="numeric" placeholder="5555" aria-label="Connect port" disabled>
        <button id="submit" type="submit" disabled>Connect</button>
      </form>
      <code>{escape(self.text)}</code>
    </section>
  </main>
  <script>
    const form = document.querySelector("#connect-form");
    const input = document.querySelector("#port");
    const button = document.querySelector("#submit");
    const statusEl = document.querySelector("#status");
    const toasterRoot = document.querySelector("#toaster-root");
    let toast = null;
    let closing = false;

    async function setupSonner() {{
      try {{
        const [React, ReactDOM, Sonner] = await Promise.all([
          import("https://esm.sh/react@18"),
          import("https://esm.sh/react-dom@18/client"),
          import("https://esm.sh/sonner?deps=react@18,react-dom@18"),
        ]);
        ReactDOM.createRoot(toasterRoot).render(
          React.createElement(Sonner.Toaster, {{
            position: "top-center",
            richColors: true,
          }})
        );
        toast = Sonner.toast;
      }} catch (error) {{
        console.warn("Sonner toast could not be loaded", error);
      }}
    }}

    setupSonner();

    async function poll() {{
      const response = await fetch("/state", {{ cache: "no-store" }});
      const state = await response.json();
      statusEl.textContent = state.deviceIp
        ? `${{state.message}} (${{state.deviceIp}})`
        : state.message;
      input.disabled = !state.canSubmit;
      button.disabled = !state.canSubmit;
      if (state.canSubmit && document.activeElement !== input) {{
        input.focus();
      }}
      if (state.done && !closing) {{
        closing = true;
        if (toast) {{
          toast.success("连接成功", {{
            description: "ADB wireless debugging connected.",
            duration: 1600,
          }});
        }}
        setTimeout(() => {{
          window.open("", "_self");
          window.close();
        }}, 2200);
      }}
    }}

    form.addEventListener("submit", async (event) => {{
      event.preventDefault();
      input.disabled = true;
      button.disabled = true;
      await fetch("/connect", {{
        method: "POST",
        headers: {{ "Content-Type": "application/x-www-form-urlencoded" }},
        body: new URLSearchParams(new FormData(form)),
      }});
      poll();
    }});

    poll();
    setInterval(poll, 800);
  </script>
</body>
</html>
"""


def display_qr_code_browser(text, ttl_seconds=QR_CACHE_TTL_SECONDS):
    """Generate a static QR code page and open it in a new browser window."""
    qr_svg = build_qr_svg(text)

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ADB Wireless Debug QR Code</title>
  <style>
    :root {{
      color-scheme: light dark;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    body {{
      align-items: center;
      background: #f5f7fb;
      color: #172033;
      display: flex;
      justify-content: center;
      margin: 0;
      min-height: 100vh;
      padding: 32px;
    }}
    main {{
      align-items: center;
      display: flex;
      flex-direction: column;
      gap: 18px;
      max-width: 720px;
      text-align: center;
    }}
    h1 {{
      font-size: 28px;
      font-weight: 700;
      margin: 0;
    }}
    .qr {{
      background: #ffffff;
      border: 1px solid #d9e0ec;
      border-radius: 8px;
      box-shadow: 0 18px 60px rgba(23, 32, 51, 0.16);
      padding: 24px;
    }}
    .qr svg {{
      display: block;
      height: min(70vw, 520px);
      width: min(70vw, 520px);
    }}
    code {{
      background: rgba(23, 32, 51, 0.08);
      border-radius: 6px;
      font-size: 14px;
      padding: 8px 10px;
      word-break: break-all;
    }}
    @media (prefers-color-scheme: dark) {{
      body {{
        background: #101522;
        color: #eef3ff;
      }}
      .qr {{
        background: #ffffff;
        border-color: #2f3a4f;
      }}
      code {{
        background: rgba(238, 243, 255, 0.12);
      }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>ADB Wireless Debug QR Code</h1>
    <div class="qr">{qr_svg}</div>
    <code>{escape(text)}</code>
  </main>
</body>
</html>
"""

    QR_CACHE_DIR.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        prefix="adb_qr_",
        suffix=".html",
        dir=QR_CACHE_DIR,
        delete=False,
    ) as html_file:
        html_file.write(html)
        html_path = Path(html_file.name)

    opened = webbrowser.open_new(html_path.resolve().as_uri())
    if opened:
        print(f"{Colors.GREEN}✓ QR code opened in browser{Colors.RESET}")
    else:
        print(f"{Colors.YELLOW}Browser did not report a successful open{Colors.RESET}")

    cleanup_timer = delete_file_later(html_path, ttl_seconds)
    return html_path, cleanup_timer


def get_connected_devices():
    """Get list of connected ADB devices."""
    result = subprocess.run("adb devices", shell=True, capture_output=True, text=True)
    devices = []
    for line in result.stdout.strip().split("\n")[1:]:
        if line.strip() and "device" in line:
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
        choice = input(
            f"\n{Colors.BOLD}Select device (1-{len(devices)}): {Colors.RESET}"
        ).strip()
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
        elif arg in ["-r", "--reverse"]:
            run_reverse()
            return
        elif arg == "--restart":
            run_restart()
            return
        elif arg in ["-d", "--devices"]:
            run_devices()
            return
        elif arg in ["-h", "--help"]:
            print(f"\n{Colors.BOLD}ADB Wireless Debug Helper{Colors.RESET}")
            print("\nUsage: python main.py [OPTIONS]")
            print("\nOptions:")
            print(
                f"  {Colors.BLUE}-c, --connect{Colors.RESET}       Scan QR to get IP, then connect (for paired devices)"
            )
            print(
                f"  {Colors.YELLOW}-r, --reverse{Colors.RESET}       Setup reverse port (tcp:8081) for selected device"
            )
            print(
                f"  {Colors.YELLOW}    --restart{Colors.RESET}       Restart ADB server (kill-server && start-server)"
            )
            print(
                f"  {Colors.GREEN}-d, --devices{Colors.RESET}       List connected devices"
            )
            print(
                f"  {Colors.YELLOW}-h, --help{Colors.RESET}          Show this help message"
            )
            return

    text = FORMAT_QR % (NAME, PASS)

    print(f"\n{Colors.BOLD}=== ADB Wireless Debug ==={Colors.RESET}\n")

    qr_code_path = None
    qr_code_cleanup_timer = None
    browser_session = None
    try:
        browser_session = BrowserPairingSession(text)
        browser_url = browser_session.start()
        opened = webbrowser.open_new(browser_url)
        if opened:
            print(f"{Colors.GREEN}✓ QR code opened in browser{Colors.RESET}")
        else:
            print(f"{Colors.YELLOW}Browser did not report a successful open{Colors.RESET}")
    except Exception as exc:
        browser_session = None
        print(f"{Colors.YELLOW}Could not open interactive browser page: {exc}{Colors.RESET}")
        try:
            qr_code_path, qr_code_cleanup_timer = display_qr_code_browser(text)
        except Exception as fallback_exc:
            print(
                f"{Colors.YELLOW}Could not open QR code in browser: {fallback_exc}{Colors.RESET}"
            )

    display_qr_code(text)

    if mode == "pair-connect":
        print(f"\n{Colors.GREEN}Mode: Pair & Connect{Colors.RESET}")
        print("1. Scan QR code to pair new device")
        print("2. Then wait for the connect port to be auto-discovered\n")
        print(
            f"{Colors.YELLOW}Path: Developer options > Wireless debugging > Pair device with QR code{Colors.RESET}"
        )
    else:
        print(f"\n{Colors.BLUE}Mode: Connect Only{Colors.RESET}")
        print("1. Make sure Wireless debugging is enabled")
        print("2. Then wait for the connect port to be auto-discovered\n")
        print(
            f"{Colors.YELLOW}Path: Developer options > Wireless debugging{Colors.RESET}"
        )

    zeroconf = Zeroconf()
    listener = ADBListener(
        mode=mode,
        zeroconf_instance=zeroconf,
        qr_code_path=qr_code_path,
        qr_code_cleanup_timer=qr_code_cleanup_timer,
        browser_session=browser_session,
    )
    browser = ServiceBrowser(zeroconf, [TYPE_PAIRING, TYPE_CONNECT], listener)

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
        if browser_session:
            import time

            time.sleep(1.5)
            browser_session.stop()
        print(f"\n{Colors.BLUE}Connected devices:{Colors.RESET}")
        subprocess.run(CMD_DEVICES, shell=True)


if __name__ == "__main__":
    main()
