#!/usr/bin/env python3
"""HA USB/IP Client WebUI — Flask backend with SocketIO for live logs."""

import json
import os
import re
import threading
import time
import urllib.request

from flask import Flask, g, jsonify, render_template, request
from flask_socketio import SocketIO

from usbip_lib.config import (
    get_addon_config,
    get_addon_state,
    list_installed_addons,
    restart_addon,
    send_ha_notification,
    set_addon_config,
)
from usbip_lib.constants import (
    EVENTS_FILE,
    SUPERVISOR_TOKEN,
    SUPERVISOR_URL,
)
from usbip_lib.events import now_iso, read_events, write_event
from usbip_lib.usbip import (
    detach_all,
    lookup_usb_name,
    parse_usbip_list,
    parse_usbip_port,
    ping_server,
    run_cmd,
)

# ---------------------------------------------------------------------------
# Constants (WebUI-specific only)
# ---------------------------------------------------------------------------
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
socketio = SocketIO(
    app,
    async_mode="gevent",
    cors_allowed_origins=["http://localhost", "http://127.0.0.1"],
)

# ---------------------------------------------------------------------------
# In-memory state
# ---------------------------------------------------------------------------
log_buffer: list[str] = []
log_lock = threading.Lock()
_log_seq: int = 0  # monotonic sequence counter for dedup
health_state: dict = {}  # server_ip -> {latency_ms, online, last_check}
health_lock = threading.Lock()


# ---------------------------------------------------------------------------
# WebUI-specific helpers
# ---------------------------------------------------------------------------
def _fetch_logs_direct() -> list[str]:
    """Fetch logs directly from Supervisor API (bypass buffer)."""
    global _log_seq
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
            # Populate buffer with new lines (sequence-based dedup)
            with log_lock:
                existing = set(f"{i}:{ln}" for i, ln in enumerate(log_buffer[-500:]))
                for idx, ln in enumerate(lines[-500:]):
                    # Use positional check: only skip if exact same content at same tail position
                    if f"{idx}:{ln}" not in existing:
                        log_buffer.append(ln)
                        _log_seq += 1
                while len(log_buffer) > LOG_BUFFER_MAX:
                    log_buffer.pop(0)
            return lines[-500:]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Background threads
# ---------------------------------------------------------------------------
def _health_checker():
    """Periodically check server health and device attachment."""
    while True:
        try:
            config = get_addon_config()
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
                latency = ping_server(srv)
                new_state[srv] = {
                    "online": latency is not None,
                    "latency_ms": latency,
                    "last_check": now_iso(),
                }
            with health_lock:
                health_state.clear()
                health_state.update(new_state)
        except Exception:
            pass
        time.sleep(HEALTH_INTERVAL)


def _log_tailer():
    """Tail the s6 log output and push to WebSocket clients."""
    global _log_seq

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
                content = re.sub(r"\x1b\[[0-9;]*m", "", content)
                lines = content.strip().split("\n")
                new_lines = []
                with log_lock:
                    # Compare tail of fetched lines against tail of buffer
                    # to find genuinely new lines
                    buf_tail = log_buffer[-500:] if log_buffer else []
                    start_idx = max(0, len(lines) - 500)
                    candidate_lines = [
                        ln.strip() for ln in lines[start_idx:] if ln.strip()
                    ]

                    # Find where new content starts by matching
                    # the last known buffer lines against the fetched tail
                    match_start = 0
                    if buf_tail and candidate_lines:
                        # Find the last buf_tail line in candidate_lines
                        last_buf = buf_tail[-1]
                        for i in range(len(candidate_lines) - 1, -1, -1):
                            if candidate_lines[i] == last_buf:
                                match_start = i + 1
                                break

                    for ln in candidate_lines[match_start:]:
                        new_lines.append(ln)
                        log_buffer.append(ln)
                        _log_seq += 1
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
    g.ingress_path = request.headers.get("X-Ingress-Path", "")


@app.context_processor
def _template_globals():
    return {
        "ingress_path": g.get("ingress_path", ""),
        "version": "0.5.0-beta",
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
    devices = parse_usbip_port()
    # Enrich with USB names
    for d in devices:
        if d.get("device_id"):
            d["usb_name"] = lookup_usb_name(d["device_id"])
    return jsonify({"ok": True, "devices": devices})


@app.route("/api/discover")
def api_discover():
    server = request.args.get("server", "").strip()
    if not server:
        return jsonify({"ok": False, "error": "server parameter required"}), 400
    devices = parse_usbip_list(server)
    for d in devices:
        d["usb_name"] = lookup_usb_name(d.get("device_id", ""))
    write_event("discover", f"Discovered {len(devices)} device(s)", server=server)
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
    run_cmd(["usbip", "detach", "-r", server, "-b", busid])
    time.sleep(0.5)

    rc, out, err = run_cmd(["usbip", "attach", "--remote", server, "--busid", busid])
    success = rc == 0
    detail = "attached" if success else (err or "unknown error")
    write_event(
        "attach_ok" if success else "attach_fail", detail, device=name, server=server
    )
    if success:
        send_ha_notification(
            "USB/IP Device Attached", f"{name} ({busid}) from {server}"
        )
    return jsonify({"ok": success, "detail": detail})


@app.route("/api/detach", methods=["POST"])
def api_detach():
    data = request.get_json(force=True)
    port = data.get("port")
    if port is None:
        return jsonify({"ok": False, "error": "port required"}), 400
    port = str(port)
    rc, out, err = run_cmd(["usbip", "detach", "-p", port])
    success = rc == 0
    detail = "detached" if success else (err or "unknown error")
    write_event(
        "detach_ok" if success else "detach_fail", detail, device=f"port {port}"
    )
    if success:
        send_ha_notification("USB/IP Device Detached", f"Port {port}")
    return jsonify({"ok": success, "detail": detail})


@app.route("/api/detach-all", methods=["POST"])
def api_detach_all():
    detached, failed = detach_all()
    write_event("detach_all", f"Detached {detached}/{detached + failed} devices")
    return jsonify({"ok": True, "detached": detached, "failed": failed})


@app.route("/api/attach-all", methods=["POST"])
def api_attach_all():
    config = get_addon_config()
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
                discovery_cache[server] = parse_usbip_list(server)
            found = [d for d in discovery_cache[server] if d["device_id"] == dev_or_bus]
            if found:
                busid = found[0]["busid"]
            else:
                results.append(
                    {
                        "name": name,
                        "ok": False,
                        "detail": f"device {dev_or_bus} not found on {server}",
                    }
                )
                continue

        run_cmd(["usbip", "detach", "-r", server, "-b", busid])
        time.sleep(0.5)
        rc, _, err = run_cmd(["usbip", "attach", "--remote", server, "--busid", busid])
        ok = rc == 0
        results.append({"name": name, "ok": ok, "detail": "attached" if ok else err})
        write_event(
            "attach_ok" if ok else "attach_fail",
            "attach-all",
            device=name,
            server=server,
        )
        time.sleep(1)

    return jsonify({"ok": True, "results": results})


@app.route("/api/config")
def api_config_get():
    config = get_addon_config()
    return jsonify({"ok": True, "config": config})


@app.route("/api/config", methods=["POST"])
def api_config_set():
    data = request.get_json(force=True)
    resp = set_addon_config(data)
    ok = resp.get("result") == "ok"
    write_event("config_change", json.dumps(data)[:200])
    return jsonify({"ok": ok, "response": resp})


@app.route("/api/config/backup")
def api_config_backup():
    config = get_addon_config()
    return jsonify(config)


@app.route("/api/config/restore", methods=["POST"])
def api_config_restore():
    data = request.get_json(force=True)
    resp = set_addon_config(data)
    ok = resp.get("result") == "ok"
    write_event("config_restore", "Configuration restored from backup")
    return jsonify({"ok": ok, "response": resp})


@app.route("/api/events")
def api_events():
    limit = request.args.get("limit", 200, type=int)
    events = read_events(limit)
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
            return jsonify(
                {
                    "ok": False,
                    "error": "Invalid subnet format. Use x.x.x.x/24 or single IP",
                }
            ), 400
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
        lat = ping_server(ip, timeout=1.5)
        if lat is not None:
            devs = parse_usbip_list(ip)
            results.append({"server": ip, "latency_ms": lat, "devices": devs})

    threads = []
    for ip in hosts[:254]:
        t = threading.Thread(target=_probe, args=(ip,), daemon=True)
        threads.append(t)
        t.start()
    for t in threads:
        t.join(timeout=5)

    write_event("scan", f"Scanned {subnet}, found {len(results)} server(s)")
    return jsonify({"ok": True, "servers": results})


@app.route("/api/usb-db")
def api_usb_db():
    vid_pid = request.args.get("id", "").strip()
    name = lookup_usb_name(vid_pid)
    return jsonify({"ok": True, "id": vid_pid, "name": name})


@app.route("/api/notify", methods=["POST"])
def api_notify():
    data = request.get_json(force=True)
    title = data.get("title", "USB/IP")
    message = data.get("message", "Test notification")
    send_ha_notification(title, message)
    return jsonify({"ok": True})


@app.route("/api/addons")
def api_addons():
    """List all installed Home Assistant add-ons."""
    addons = list_installed_addons()
    return jsonify({"ok": True, "addons": addons})


@app.route("/api/addon-health")
def api_addon_health():
    """Check health of configured dependent add-ons."""
    config = get_addon_config()
    dependent = config.get("dependent_addons", [])
    results = []
    for addon in dependent:
        slug = addon.get("slug", "")
        name = addon.get("name", slug)
        if not slug:
            continue
        state = get_addon_state(slug)
        results.append({"slug": slug, "name": name, "state": state})
    return jsonify({"ok": True, "addons": results})


@app.route("/api/addon-restart", methods=["POST"])
def api_addon_restart():
    """Restart a specific add-on by slug."""
    data = request.get_json(force=True)
    slug = data.get("slug", "").strip()
    if not slug:
        return jsonify({"ok": False, "error": "slug required"}), 400
    ok = restart_addon(slug)
    return jsonify({"ok": ok})


@app.route("/api/dependent-addons", methods=["POST"])
def api_dependent_addons_save():
    """Save dependent add-ons selection to add-on config."""
    data = request.get_json(force=True)
    addons_list = data.get("dependent_addons", [])
    config = get_addon_config()
    config["dependent_addons"] = addons_list
    resp = set_addon_config(config)
    ok = resp.get("result") == "ok"
    write_event(
        "config_change", f"Updated dependent add-ons: {len(addons_list)} selected"
    )
    return jsonify({"ok": ok})


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

    write_event("webui_start", "WebUI service started")

    socketio.run(
        app,
        host="0.0.0.0",
        port=8099,
        debug=False,
        use_reloader=False,
        log_output=False,
    )
