#!/usr/bin/env python3
"""HA USB/IP Client WebUI — Flask backend with SocketIO for live logs."""

import json
import os
import re
import socket
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EVENTS_FILE = "/tmp/usbip_events.jsonl"
DEVICE_DETAILS_FILE = "/tmp/device_details.txt"
ATTACHED_DEVICES_FILE = "/tmp/attached_devices.txt"
USB_IDS_FILE = "/usr/share/hwdata/usb.ids"
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
SUPERVISOR_URL = "http://supervisor"
LOG_BUFFER_MAX = 2000
HEALTH_INTERVAL = 30  # seconds

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = Flask(
    __name__,
    template_folder="/usr/local/bin/webui/templates",
    static_folder="/usr/local/bin/webui/static",
)
app.config["SECRET_KEY"] = os.urandom(24).hex()
socketio = SocketIO(app, async_mode="gevent", cors_allowed_origins="*")

# ---------------------------------------------------------------------------
# In-memory state
# ---------------------------------------------------------------------------
log_buffer: list[str] = []
log_lock = threading.Lock()
health_state: dict = {}  # server_ip -> {latency_ms, online, last_check}
health_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_event(event_type: str, detail: str, device: str = "", server: str = ""):
    """Append an event to the JSONL event log."""
    entry = {
        "ts": _now_iso(),
        "type": event_type,
        "device": device,
        "server": server,
        "detail": detail,
    }
    try:
        with open(EVENTS_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def _read_events(limit: int = 200) -> list[dict]:
    """Read most-recent events from the JSONL file."""
    if not os.path.exists(EVENTS_FILE):
        return []
    try:
        with open(EVENTS_FILE, "r") as f:
            lines = f.readlines()
        events = []
        for ln in lines[-limit:]:
            ln = ln.strip()
            if ln:
                try:
                    events.append(json.loads(ln))
                except json.JSONDecodeError:
                    pass
        return events
    except OSError:
        return []


def _run(cmd: list[str], timeout: int = 15) -> tuple[int, str, str]:
    """Run a subprocess and return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


def _parse_usbip_port() -> list[dict]:
    """Parse `usbip port` output into structured data."""
    rc, out, _ = _run(["usbip", "port"])
    if rc != 0 or not out.strip():
        return []
    devices = []
    current: dict | None = None
    for line in out.splitlines():
        m = re.match(r"^Port (\d+):\s*<(.+?)>\s*(.*)", line)
        if m:
            if current:
                devices.append(current)
            current = {
                "port": int(m.group(1)),
                "status": m.group(2).strip(),
                "info": m.group(3).strip(),
                "busid": "",
                "device_id": "",
            }
            continue
        if current:
            stripped = line.strip()
            # line like: "1-1 -> usbip://192.168.1.44:3240/1-1.4"
            bm = re.search(r"usbip://([^/]+)/([^\s]+)", stripped)
            if bm:
                current["server"] = bm.group(1).split(":")[0]
                current["remote_busid"] = bm.group(2)
            # line with device id
            dm = re.search(r"([0-9a-fA-F]{4}:[0-9a-fA-F]{4})", stripped)
            if dm:
                current["device_id"] = dm.group(1)
    if current:
        devices.append(current)
    return devices


def _parse_usbip_list(server: str) -> list[dict]:
    """Parse `usbip list -r <server>` into structured data."""
    rc, out, err = _run(["usbip", "list", "-r", server])
    if rc != 0:
        return []
    devices = []
    for line in out.splitlines():
        m = re.match(
            r"^\s*([0-9][0-9.\-]+):\s*(.+)\s+\(([0-9a-fA-F]{4}:[0-9a-fA-F]{4})\)\s*$",
            line,
        )
        if m:
            devices.append(
                {
                    "busid": m.group(1).strip(),
                    "name": m.group(2).strip(),
                    "device_id": m.group(3).strip(),
                    "server": server,
                }
            )
    return devices


def _lookup_usb_name(vendor_product: str) -> str:
    """Resolve vendor:product from usb.ids database."""
    if not os.path.exists(USB_IDS_FILE):
        return vendor_product
    parts = vendor_product.lower().split(":")
    if len(parts) != 2:
        return vendor_product
    vid, pid = parts
    vendor_name = ""
    try:
        with open(USB_IDS_FILE, "r", errors="replace") as f:
            in_vendor = False
            for line in f:
                if line.startswith("#") or not line.strip():
                    continue
                if not line.startswith("\t"):
                    # vendor line
                    if line[:4].lower() == vid:
                        vendor_name = line[4:].strip()
                        in_vendor = True
                        continue
                    elif in_vendor:
                        break
                elif in_vendor and line.startswith("\t") and not line.startswith(
                    "\t\t"
                ):
                    if line.strip()[:4].lower() == pid:
                        product_name = line.strip()[4:].strip()
                        return f"{vendor_name} {product_name}"
    except OSError:
        pass
    return vendor_name if vendor_name else vendor_product


def _supervisor_request(method: str, path: str, json_data: dict | None = None):
    """Make a request to the HA Supervisor API."""
    import urllib.request

    url = f"{SUPERVISOR_URL}{path}"
    headers = {
        "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
        "Content-Type": "application/json",
    }
    data = json.dumps(json_data).encode() if json_data else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"result": "error", "message": str(e)}


def _get_addon_config() -> dict:
    """Read current addon options from Supervisor."""
    resp = _supervisor_request("GET", "/addons/self/info")
    if resp.get("result") == "ok":
        return resp.get("data", {}).get("options", {})
    return {}


def _set_addon_config(options: dict) -> dict:
    """Write addon options via Supervisor."""
    return _supervisor_request("POST", "/addons/self/options", {"options": options})


def _send_ha_notification(title: str, message: str):
    """Send a persistent notification to Home Assistant."""
    _supervisor_request(
        "POST",
        "/core/api/services/persistent_notification/create",
        {"title": title, "message": message},
    )


def _fetch_logs_direct() -> list[str]:
    """Fetch logs directly from Supervisor API (bypass buffer)."""
    import urllib.request

    try:
        url = f"{SUPERVISOR_URL}/addons/self/logs"
        headers = {
            "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
            "Accept": "text/plain",
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError:
                content = raw.decode("latin-1", errors="replace")
            content = re.sub(r"\x1b\[[0-9;]*m", "", content)
            lines = [ln.strip() for ln in content.strip().split("\n") if ln.strip()]
            # Also populate buffer for future calls
            with log_lock:
                for ln in lines[-500:]:
                    if ln not in log_buffer[-50:]:
                        log_buffer.append(ln)
                while len(log_buffer) > LOG_BUFFER_MAX:
                    log_buffer.pop(0)
            return lines[-500:]
    except Exception:
        return []


def _ping_server(host: str, port: int = 3240, timeout: float = 2.0) -> float | None:
    """Try TCP connect to a USB/IP server. Returns latency in ms or None."""
    try:
        start = time.monotonic()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        latency = (time.monotonic() - start) * 1000
        s.close()
        return round(latency, 1)
    except (OSError, socket.error):
        return None


# ---------------------------------------------------------------------------
# Background threads
# ---------------------------------------------------------------------------
def _health_checker():
    """Periodically check server health and device attachment."""
    while True:
        try:
            config = _get_addon_config()
            servers = set()
            default_srv = config.get("usbipd_server_address", "")
            if default_srv:
                servers.add(default_srv)
            for dev in config.get("devices", []):
                srv = dev.get("server")
                if srv:
                    servers.add(srv)

            new_state = {}
            for srv in servers:
                latency = _ping_server(srv)
                new_state[srv] = {
                    "online": latency is not None,
                    "latency_ms": latency,
                    "last_check": _now_iso(),
                }
            with health_lock:
                health_state.clear()
                health_state.update(new_state)
        except Exception:
            pass
        time.sleep(HEALTH_INTERVAL)


def _log_tailer():
    """Tail the s6 log output and push to WebSocket clients."""
    import urllib.request

    while True:
        try:
            url = f"{SUPERVISOR_URL}/addons/self/logs"
            headers = {
                "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
                "Accept": "text/plain",
            }
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                # Try utf-8, fallback to latin-1
                try:
                    content = raw.decode("utf-8")
                except UnicodeDecodeError:
                    content = raw.decode("latin-1", errors="replace")
                # Strip ANSI escape codes
                import re as _re
                content = _re.sub(r"\x1b\[[0-9;]*m", "", content)
                lines = content.strip().split("\n")
                new_lines = []
                with log_lock:
                    buf_len = len(log_buffer)
                    # Take only lines beyond what we already have
                    start_idx = max(0, len(lines) - 500)
                    for ln in lines[start_idx:]:
                        cleaned = ln.strip()
                        if not cleaned:
                            continue
                        # Simple dedup: skip if it matches the last N buffer entries
                        if buf_len > 0 and cleaned == log_buffer[-1]:
                            continue
                        if cleaned not in set(log_buffer[-50:]):
                            new_lines.append(cleaned)
                            log_buffer.append(cleaned)
                            buf_len += 1
                    # Trim buffer
                    while len(log_buffer) > LOG_BUFFER_MAX:
                        log_buffer.pop(0)
                for ln in new_lines:
                    try:
                        socketio.emit("log_line", {"line": ln}, namespace="/ws/logs")
                    except Exception:
                        pass
        except Exception as e:
            # Log the error to buffer itself for debugging
            err_line = f"[WebUI] Log tailer error: {e}"
            with log_lock:
                if err_line not in log_buffer[-5:]:
                    log_buffer.append(err_line)
        time.sleep(3)


# ---------------------------------------------------------------------------
# Flask middleware — inject ingress_path
# ---------------------------------------------------------------------------
@app.before_request
def _inject_ingress():
    request.ingress_path = request.headers.get("X-Ingress-Path", "")


@app.context_processor
def _template_globals():
    return {
        "ingress_path": getattr(request, "ingress_path", ""),
        "version": "0.4.1",
    }


# ---------------------------------------------------------------------------
# Routes — Pages
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Routes — API
# ---------------------------------------------------------------------------
@app.route("/api/status")
def api_status():
    devices = _parse_usbip_port()
    # Enrich with USB names
    for d in devices:
        if d.get("device_id"):
            d["usb_name"] = _lookup_usb_name(d["device_id"])
    return jsonify({"ok": True, "devices": devices})


@app.route("/api/discover")
def api_discover():
    server = request.args.get("server", "").strip()
    if not server:
        return jsonify({"ok": False, "error": "server parameter required"}), 400
    devices = _parse_usbip_list(server)
    for d in devices:
        d["usb_name"] = _lookup_usb_name(d.get("device_id", ""))
    _write_event("discover", f"Discovered {len(devices)} device(s)", server=server)
    return jsonify({"ok": True, "devices": devices, "server": server})


@app.route("/api/attach", methods=["POST"])
def api_attach():
    data = request.get_json(force=True)
    server = data.get("server", "").strip()
    busid = data.get("busid", "").strip()
    name = data.get("name", busid)
    if not server or not busid:
        return jsonify({"ok": False, "error": "server and busid required"}), 400

    # Pre-detach
    _run(["usbip", "detach", "-r", server, "-b", busid])
    time.sleep(0.5)

    rc, out, err = _run(["usbip", "attach", "--remote", server, "--busid", busid])
    success = rc == 0
    detail = "attached" if success else (err or "unknown error")
    _write_event(
        "attach_ok" if success else "attach_fail", detail, device=name, server=server
    )
    if success:
        _send_ha_notification("USB/IP Device Attached", f"{name} ({busid}) from {server}")
    return jsonify({"ok": success, "detail": detail})


@app.route("/api/detach", methods=["POST"])
def api_detach():
    data = request.get_json(force=True)
    port = data.get("port")
    if port is None:
        return jsonify({"ok": False, "error": "port required"}), 400
    port = str(port)
    rc, out, err = _run(["usbip", "detach", "-p", port])
    success = rc == 0
    detail = "detached" if success else (err or "unknown error")
    _write_event("detach_ok" if success else "detach_fail", detail, device=f"port {port}")
    if success:
        _send_ha_notification("USB/IP Device Detached", f"Port {port}")
    return jsonify({"ok": success, "detail": detail})


@app.route("/api/detach-all", methods=["POST"])
def api_detach_all():
    devices = _parse_usbip_port()
    results = []
    for d in devices:
        port = str(d["port"])
        rc, _, err = _run(["usbip", "detach", "-p", port])
        results.append({"port": d["port"], "ok": rc == 0})
        time.sleep(0.5)
    ok_count = sum(1 for r in results if r["ok"])
    _write_event("detach_all", f"Detached {ok_count}/{len(results)} devices")
    return jsonify({"ok": True, "results": results})


@app.route("/api/attach-all", methods=["POST"])
def api_attach_all():
    config = _get_addon_config()
    default_server = config.get("usbipd_server_address", "")
    devices = config.get("devices", [])
    results = []

    # Build discovery cache keyed by server
    discovery_cache: dict[str, list[dict]] = {}

    for dev in devices:
        name = dev.get("name", "")
        dev_or_bus = dev.get("device_or_bus_id", "")
        server = dev.get("server") or default_server
        if not dev_or_bus or not server:
            results.append({"name": name, "ok": False, "detail": "missing config"})
            continue

        # Resolve device_id to bus_id if needed
        busid = dev_or_bus
        if re.match(r"^[0-9a-fA-F]{4}:[0-9a-fA-F]{4}$", dev_or_bus):
            if server not in discovery_cache:
                discovery_cache[server] = _parse_usbip_list(server)
            found = [d for d in discovery_cache[server] if d["device_id"] == dev_or_bus]
            if found:
                busid = found[0]["busid"]
            else:
                results.append({"name": name, "ok": False, "detail": f"device {dev_or_bus} not found on {server}"})
                continue

        _run(["usbip", "detach", "-r", server, "-b", busid])
        time.sleep(0.5)
        rc, _, err = _run(["usbip", "attach", "--remote", server, "--busid", busid])
        ok = rc == 0
        results.append({"name": name, "ok": ok, "detail": "attached" if ok else err})
        _write_event("attach_ok" if ok else "attach_fail", "attach-all", device=name, server=server)
        time.sleep(1)

    return jsonify({"ok": True, "results": results})


@app.route("/api/config")
def api_config_get():
    config = _get_addon_config()
    return jsonify({"ok": True, "config": config})


@app.route("/api/config", methods=["POST"])
def api_config_set():
    data = request.get_json(force=True)
    resp = _set_addon_config(data)
    ok = resp.get("result") == "ok"
    _write_event("config_change", json.dumps(data)[:200])
    return jsonify({"ok": ok, "response": resp})


@app.route("/api/config/backup")
def api_config_backup():
    config = _get_addon_config()
    return jsonify(config)


@app.route("/api/config/restore", methods=["POST"])
def api_config_restore():
    data = request.get_json(force=True)
    resp = _set_addon_config(data)
    ok = resp.get("result") == "ok"
    _write_event("config_restore", "Configuration restored from backup")
    return jsonify({"ok": ok, "response": resp})


@app.route("/api/events")
def api_events():
    limit = request.args.get("limit", 200, type=int)
    events = _read_events(limit)
    return jsonify({"ok": True, "events": events})


@app.route("/api/events/clear", methods=["POST"])
def api_events_clear():
    try:
        open(EVENTS_FILE, "w").close()
    except OSError:
        pass
    return jsonify({"ok": True})


@app.route("/api/health")
def api_health():
    with health_lock:
        state = dict(health_state)
    return jsonify({"ok": True, "servers": state})


@app.route("/api/scan", methods=["POST"])
def api_scan():
    data = request.get_json(force=True)
    subnet = data.get("subnet", "").strip()
    if not subnet:
        return jsonify({"ok": False, "error": "subnet required"}), 400

    # Parse CIDR: 192.168.1.0/24
    m = re.match(r"^(\d+\.\d+\.\d+)\.(\d+)/(\d+)$", subnet)
    if not m:
        # Try single IP
        if re.match(r"^\d+\.\d+\.\d+\.\d+$", subnet):
            hosts = [subnet]
        else:
            return jsonify({"ok": False, "error": "Invalid subnet format. Use x.x.x.x/24 or single IP"}), 400
    else:
        base = m.group(1)
        prefix = int(m.group(3))
        if prefix < 24:
            return jsonify({"ok": False, "error": "Minimum /24 subnet for safety"}), 400
        host_count = 2 ** (32 - prefix)
        start_host = int(m.group(2))
        hosts = [f"{base}.{start_host + i}" for i in range(1, min(host_count - 1, 255))]

    results = []

    def _probe(ip):
        lat = _ping_server(ip, timeout=1.5)
        if lat is not None:
            devs = _parse_usbip_list(ip)
            results.append({"server": ip, "latency_ms": lat, "devices": devs})

    threads = []
    for ip in hosts[:254]:
        t = threading.Thread(target=_probe, args=(ip,), daemon=True)
        threads.append(t)
        t.start()
    for t in threads:
        t.join(timeout=5)

    _write_event("scan", f"Scanned {subnet}, found {len(results)} server(s)")
    return jsonify({"ok": True, "servers": results})


@app.route("/api/usb-db")
def api_usb_db():
    vid_pid = request.args.get("id", "").strip()
    name = _lookup_usb_name(vid_pid)
    return jsonify({"ok": True, "id": vid_pid, "name": name})


@app.route("/api/notify", methods=["POST"])
def api_notify():
    data = request.get_json(force=True)
    title = data.get("title", "USB/IP")
    message = data.get("message", "Test notification")
    _send_ha_notification(title, message)
    return jsonify({"ok": True})


@app.route("/api/logs")
def api_logs():
    level = request.args.get("level", "").lower()
    # Try buffer first, fallback to direct Supervisor fetch
    with log_lock:
        lines = list(log_buffer)
    if not lines:
        # Buffer empty — fetch directly from Supervisor
        lines = _fetch_logs_direct()
    if level:
        lines = [ln for ln in lines if level in ln.lower()]
    return jsonify({"ok": True, "lines": lines[-500:]})


# ---------------------------------------------------------------------------
# WebSocket — live logs
# ---------------------------------------------------------------------------
@socketio.on("connect", namespace="/ws/logs")
def ws_logs_connect():
    # Send buffered lines on connect
    with log_lock:
        for ln in log_buffer[-200:]:
            socketio.emit("log_line", {"line": ln}, namespace="/ws/logs")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Start background threads
    threading.Thread(target=_health_checker, daemon=True).start()
    threading.Thread(target=_log_tailer, daemon=True).start()

    _write_event("webui_start", "WebUI service started")

    socketio.run(
        app,
        host="0.0.0.0",
        port=8099,
        debug=False,
        use_reloader=False,
        log_output=False,
    )
