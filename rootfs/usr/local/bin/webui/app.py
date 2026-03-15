#!/usr/bin/env python3
"""HA USB/IP Client WebUI — Flask backend with SocketIO for live logs."""

import json
import os
import re
import signal
import atexit
import threading
import time
import urllib.request

from flask import Flask, g, jsonify, make_response, render_template, request
from flask_socketio import SocketIO

from usbip_lib.config import (
    get_app_config,
    get_app_state,
    get_unique_servers,
    list_installed_apps,
    normalize_dependent_apps_config,
    normalize_notification_config,
    restart_app,
    send_ha_notification,
    set_app_config,
)
from usbip_lib.constants import (
    HEALTH_INTERVAL_SECONDS,
    EVENTS_FILE,
    LATENCY_CHANGE_ABS_THRESHOLD_MS,
    LATENCY_CHANGE_REL_THRESHOLD,
    LATENCY_FLUSH_INTERVAL_SECONDS,
    LATENCY_HEARTBEAT_SECONDS,
    LATENCY_HISTORY_FILE,
    LATENCY_HISTORY_WINDOW_SECONDS,
    SUPERVISOR_TOKEN,
    SUPERVISOR_URL,
)
from usbip_lib.events import now_iso, read_events, write_event
from usbip_lib.latency_history import (
    append_latency_samples,
    read_latency_window,
    should_persist_change,
)
from usbip_lib.usbip import (
    attach_device,
    detach_device,
    detach_all,
    is_device_id,
    lookup_usb_name,
    parse_usbip_list,
    parse_usbip_port,
    ping_server,
    resolve_device_id_to_bus_id,
    run_cmd,
)

# ---------------------------------------------------------------------------
# Constants (WebUI-specific only)
# ---------------------------------------------------------------------------
APP_VERSION = "0.5.2-beta.7"
LOG_BUFFER_MAX = 2000
VALID_WEBUI_TABS = {
    "dashboard",
    "devices",
    "discovery",
    "logs",
    "events",
    "config",
}
FLAPPING_LEVEL_RANK = {"none": 0, "warning": 1, "critical": 2}

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
latency_lock = threading.Lock()
latency_buffer: list[dict] = []
last_persisted_latency: dict[str, float | None] = {}
last_latency_flush_ts: float = 0.0
last_latency_heartbeat_ts: float = 0.0


def _flush_latency_buffer(force: bool = False) -> bool:
    """Flush buffered latency samples to persistent JSONL history file."""
    global last_latency_flush_ts

    with latency_lock:
        if not latency_buffer:
            return True

        now_ts = time.time()
        if (not force) and (
            now_ts - last_latency_flush_ts < LATENCY_FLUSH_INTERVAL_SECONDS
        ):
            return True

        batch = list(latency_buffer)

    ok = append_latency_samples(
        batch,
        history_file=LATENCY_HISTORY_FILE,
        window_seconds=LATENCY_HISTORY_WINDOW_SECONDS,
    )
    if not ok:
        return False

    with latency_lock:
        if len(latency_buffer) >= len(batch) and latency_buffer[: len(batch)] == batch:
            del latency_buffer[: len(batch)]
        else:
            latency_buffer.clear()
        last_latency_flush_ts = now_ts
    return True


def _merge_pending_latency_samples(history: dict, pending_samples: list[dict]) -> dict:
    """Merge unflushed in-memory latency samples into API history payload."""
    timestamps = list(history.get("timestamps", []))
    series_in = history.get("series", {})
    series: dict[str, list[float | None]] = {
        str(server): list(values or []) for server, values in series_in.items()
    }

    # Keep all series aligned with current timestamp length.
    for server in list(series.keys()):
        if len(series[server]) < len(timestamps):
            series[server].extend([None] * (len(timestamps) - len(series[server])))

    seen_timestamps = set(timestamps)
    for sample in pending_samples:
        ts = sample.get("ts")
        if not ts or ts in seen_timestamps:
            continue

        sample_servers = sample.get("servers") if isinstance(sample, dict) else {}
        if not isinstance(sample_servers, dict):
            sample_servers = {}

        for server in sample_servers.keys():
            server_name = str(server)
            if server_name not in series:
                series[server_name] = [None] * len(timestamps)

        timestamps.append(ts)
        seen_timestamps.add(ts)
        for server in list(series.keys()):
            series[server].append(sample_servers.get(server))

    return {
        "window_seconds": history.get("window_seconds", LATENCY_HISTORY_WINDOW_SECONDS),
        "sample_interval_seconds": history.get(
            "sample_interval_seconds", HEALTH_INTERVAL_SECONDS
        ),
        "timestamps": timestamps,
        "series": series,
    }


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


def _classify_usbip_error(raw_error: str, server: str = "", target: str = "") -> str:
    """Convert low-level usbip errors to actionable user-facing messages."""
    error = (raw_error or "").strip()
    lowered = error.lower()

    if not lowered:
        return "Operation failed. Check logs for details."

    if "timeout" in lowered:
        return (
            f"Timed out while contacting {server}. "
            "Check server reachability and port 3240."
        )
    if any(
        token in lowered
        for token in [
            "connection refused",
            "no route",
            "host unreachable",
            "name or service not known",
            "failed to connect",
        ]
    ):
        return f"Cannot reach USB/IP server {server}. Verify address and network."
    if "not found" in lowered:
        if target:
            return (
                f"Device {target} was not found on {server}. Run Discovery and retry."
            )
        return "Requested device was not found on the USB/IP server."
    if "busy" in lowered:
        return "Device is busy on the remote host. Detach it there and retry."
    if "permission denied" in lowered or "operation not permitted" in lowered:
        return (
            "Operation blocked by permissions. Verify addon privileges and "
            "AppArmor policy."
        )

    return error


def _build_flapping_warning_state(limit: int = 500) -> dict:
    """Build active flapping warning state from recent events."""
    active_by_key: dict[str, dict] = {}

    for event in read_events(limit):
        event_type = event.get("type", "")
        payload = event.get("data", {})
        if not isinstance(payload, dict):
            payload = {}

        device_key = payload.get("device_key")
        if not device_key:
            device_key = f"{event.get('server', '')}:{event.get('device', '')}"

        if event_type == "flap_cleared":
            active_by_key.pop(device_key, None)
            continue

        if event_type not in {"flap_warning", "flap_critical"}:
            continue

        level = payload.get("level", "warning")
        if level not in {"warning", "critical"}:
            level = "warning"

        active_by_key[device_key] = {
            "device_key": device_key,
            "device": event.get("device", ""),
            "server": event.get("server", ""),
            "level": level,
            "count": payload.get("count"),
            "window_seconds": payload.get("window_seconds"),
            "last_event_ts": event.get("ts", ""),
        }

    active_devices = sorted(
        active_by_key.values(),
        key=lambda item: (
            FLAPPING_LEVEL_RANK.get(item.get("level", "none"), 0),
            item.get("device_key", ""),
        ),
        reverse=True,
    )

    highest_level = "none"
    for item in active_devices:
        if item.get("level") == "critical":
            highest_level = "critical"
            break
        if item.get("level") == "warning":
            highest_level = "warning"

    return {
        "total": len(active_devices),
        "highest_level": highest_level,
        "devices": active_devices,
    }


# ---------------------------------------------------------------------------
# Background threads
# ---------------------------------------------------------------------------
def _health_checker():
    """Periodically check server health and device attachment."""
    global last_latency_heartbeat_ts

    while True:
        try:
            config = get_app_config()
            servers = get_unique_servers(config)

            new_state = {}
            sample_servers: dict[str, float | None] = {}
            for srv in servers:
                latency = ping_server(srv)
                sample_servers[srv] = latency
                new_state[srv] = {
                    "online": latency is not None,
                    "latency_ms": latency,
                    "last_check": now_iso(),
                }
            with health_lock:
                health_state.clear()
                health_state.update(new_state)

            sample = {
                "ts": now_iso(),
                "servers": sample_servers,
            }

            with latency_lock:
                latency_buffer.append(sample)
                now_ts = time.time()

                changed = False
                for srv, current in sample_servers.items():
                    previous = last_persisted_latency.get(srv)
                    if should_persist_change(
                        previous,
                        current,
                        abs_threshold_ms=LATENCY_CHANGE_ABS_THRESHOLD_MS,
                        rel_threshold=LATENCY_CHANGE_REL_THRESHOLD,
                    ):
                        changed = True
                    last_persisted_latency[srv] = current

                heartbeat_due = (
                    now_ts - last_latency_heartbeat_ts
                ) >= LATENCY_HEARTBEAT_SECONDS
                flush_due = (
                    now_ts - last_latency_flush_ts
                ) >= LATENCY_FLUSH_INTERVAL_SECONDS

            if changed or heartbeat_due or flush_due:
                if _flush_latency_buffer(force=True) and heartbeat_due:
                    with latency_lock:
                        last_latency_heartbeat_ts = now_ts
        except Exception:
            pass
        time.sleep(HEALTH_INTERVAL_SECONDS)


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


@app.after_request
def _set_api_no_cache_headers(response):
    try:
        path = request.path or ""
        ingress = ""
        try:
            ingress = g.get("ingress_path", "") or ""
        except Exception:
            ingress = ""

        # Consider both direct and ingress-prefixed paths. This ensures
        # responses served through Home Assistant Ingress still receive
        # no-cache headers for API and static endpoints.
        should_no_cache = False
        if path == "/":
            should_no_cache = True
        for prefix in ("/api/", "/static/"):
            if path.startswith(prefix) or (
                ingress and path.startswith(ingress + prefix)
            ):
                should_no_cache = True
                break

        if should_no_cache:
            response.headers["Cache-Control"] = (
                "no-store, no-cache, must-revalidate, max-age=0"
            )
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
    except Exception:
        # Be defensive: never raise from after_request middleware
        pass
    return response


@app.context_processor
def _template_globals():
    asset_stamp = "0"
    try:
        static_root = app.static_folder or ""
        static_assets = [
            os.path.join(static_root, "app.js"),
            os.path.join(static_root, "style.css"),
        ]
        mtimes = [
            os.path.getmtime(path) for path in static_assets if os.path.exists(path)
        ]
        if mtimes:
            asset_stamp = str(int(max(mtimes)))
    except OSError:
        pass
    # Access `g` defensively — templates may be rendered outside an active
    # request context in some tests or tooling; fall back to empty ingress.
    try:
        ingress_path = g.get("ingress_path", "")
    except Exception:
        ingress_path = ""

    return {
        "ingress_path": ingress_path,
        "version": APP_VERSION,
        "asset_stamp": asset_stamp,
    }


# ---------------------------------------------------------------------------
# Routes — Pages
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    requested_tab = request.args.get("tab", "").strip().lower()
    cookie_tab = request.cookies.get("usbip_active_tab", "dashboard")
    active_tab = requested_tab or cookie_tab
    if active_tab not in VALID_WEBUI_TABS:
        active_tab = "dashboard"

    initial_events: list[dict] = []
    if active_tab == "events":
        initial_events = list(reversed(read_events(200)))

    response = make_response(
        render_template(
            "index.html",
            active_tab=active_tab,
            initial_events=initial_events,
        )
    )
    response.set_cookie("usbip_active_tab", active_tab, path="/", samesite="Lax")
    return response


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
    return jsonify(
        {
            "ok": True,
            "devices": devices,
            "warnings": {"flapping": _build_flapping_warning_state()},
        }
    )


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
    success = attach_device(server=server, bus_id=busid, device_name=name)
    detail = (
        "attached"
        if success
        else _classify_usbip_error("", server=server, target=busid)
    )
    write_event(
        "attach_ok" if success else "attach_fail", detail, device=name, server=server
    )
    if success:
        send_ha_notification(
            "USB/IP Device Attached",
            f"{name} ({busid}) from {server}",
            notification_type="device_attached",
        )
    return jsonify({"ok": success, "detail": detail})


@app.route("/api/detach", methods=["POST"])
def api_detach():
    data = request.get_json(force=True)
    port = data.get("port")
    if port is None:
        return jsonify({"ok": False, "error": "port required"}), 400
    port = str(port)
    success = detach_device(port)
    detail = "detached" if success else _classify_usbip_error("", target=f"port {port}")
    write_event(
        "detach_ok" if success else "detach_fail", detail, device=f"port {port}"
    )
    if success:
        send_ha_notification(
            "USB/IP Device Detached",
            f"Port {port}",
            notification_type="device_detached",
        )
    return jsonify({"ok": success, "detail": detail})


@app.route("/api/detach-all", methods=["POST"])
def api_detach_all():
    detached, failed = detach_all()
    write_event("detach_all", f"Detached {detached}/{detached + failed} devices")
    return jsonify({"ok": True, "detached": detached, "failed": failed})


@app.route("/api/attach-all", methods=["POST"])
def api_attach_all():
    config = get_app_config()
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
            results.append(
                {
                    "name": name,
                    "ok": False,
                    "detail": "Missing config: server and device_or_bus_id are required",
                }
            )
            continue

        # Resolve device_id to bus_id if needed
        busid = dev_or_bus
        if is_device_id(dev_or_bus):
            if server not in discovery_cache:
                discovery_cache[server] = parse_usbip_list(server)
            resolved_busid = resolve_device_id_to_bus_id(
                server, dev_or_bus, discovery_cache[server]
            )
            if not resolved_busid:
                results.append(
                    {
                        "name": name,
                        "ok": False,
                        "detail": f"device {dev_or_bus} not found on {server}",
                    }
                )
                continue
            busid = resolved_busid

        run_cmd(["usbip", "detach", "-r", server, "-b", busid])
        time.sleep(0.5)
        rc, out, err = run_cmd(
            ["usbip", "attach", "--remote", server, "--busid", busid]
        )
        ok = rc == 0
        results.append(
            {
                "name": name,
                "ok": ok,
                "detail": (
                    "attached"
                    if ok
                    else _classify_usbip_error(err or out, server=server, target=busid)
                ),
            }
        )
        write_event(
            "attach_ok" if ok else "attach_fail",
            "attach-all",
            device=name,
            server=server,
        )
        time.sleep(1)

    return jsonify({"ok": True, "results": results})


@app.route("/api/diagnostics")
def api_diagnostics():
    """Return lightweight first-run diagnostics for dashboard visibility."""
    config = get_app_config()
    default_server = config.get("usbipd_server_address", "").strip()

    module_loaded = os.path.exists("/sys/module/vhci_hcd")
    cmd_rc, _, _ = run_cmd(["which", "usbip"], timeout=5)
    usbip_available = cmd_rc == 0

    server_latency = None
    discoverable_count = None
    if default_server:
        server_latency = ping_server(default_server, timeout=1.5)
        if server_latency is not None:
            discoverable_count = len(parse_usbip_list(default_server))

    return jsonify(
        {
            "ok": True,
            "checks": {
                "vhci_module_loaded": module_loaded,
                "usbip_command_available": usbip_available,
                "default_server_configured": bool(default_server),
                "default_server_reachable": server_latency is not None
                if default_server
                else None,
                "discoverable_devices": discoverable_count,
            },
            "default_server": default_server,
            "server_latency_ms": server_latency,
        }
    )


@app.route("/api/config")
def api_config_get():
    config = get_app_config()
    return jsonify({"ok": True, "config": config})


@app.route("/api/config", methods=["POST"])
def api_config_set():
    data = request.get_json(force=True)
    data, _ = normalize_dependent_apps_config(data)
    data, _ = normalize_notification_config(data)
    resp = set_app_config(data)
    ok = resp.get("result") == "ok"

    detail = ""
    if ok:
        persisted = get_app_config()
        persisted, _ = normalize_notification_config(persisted)

        expected_enabled = data.get("notifications_enabled", True)
        expected_types = set(data.get("notification_types", []))
        persisted_enabled = persisted.get("notifications_enabled", True)
        persisted_types = set(persisted.get("notification_types", []))

        if persisted_enabled != expected_enabled or persisted_types != expected_types:
            ok = False
            detail = (
                "Notification settings were not persisted by Supervisor. "
                "If the app schema changed, reinstall the app to apply "
                "the new schema."
            )

    write_event("config_change", json.dumps(data)[:200])
    return jsonify({"ok": ok, "response": resp, "detail": detail})


@app.route("/api/config/backup")
def api_config_backup():
    config = get_app_config()
    return jsonify(config)


@app.route("/api/config/restore", methods=["POST"])
def api_config_restore():
    data = request.get_json(force=True)
    data, _ = normalize_dependent_apps_config(data)
    data, _ = normalize_notification_config(data)
    resp = set_app_config(data)
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
    server_ips = sorted(state.keys()) if state else None
    history = read_latency_window(
        server_ips=server_ips,
        history_file=LATENCY_HISTORY_FILE,
        window_seconds=LATENCY_HISTORY_WINDOW_SECONDS,
    )
    if not history.get("timestamps") and state:
        history = {
            "window_seconds": LATENCY_HISTORY_WINDOW_SECONDS,
            "sample_interval_seconds": HEALTH_INTERVAL_SECONDS,
            "timestamps": [now_iso()],
            "series": {
                server_ip: [payload.get("latency_ms")]
                for server_ip, payload in state.items()
            },
        }

    with latency_lock:
        pending_samples = list(latency_buffer)
    if pending_samples:
        history = _merge_pending_latency_samples(history, pending_samples)

    return jsonify({"ok": True, "servers": state, "history": history})


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


@app.route("/api/system/restart", methods=["POST"])
def api_system_restart():
    """Schedule app restart via Supervisor and return immediately."""
    write_event("app", "User requested app restart from WebUI")

    def _restart_self_async() -> None:
        # Small delay allows HTTP response to be sent before container restarts.
        time.sleep(0.2)
        if restart_app("self"):
            write_event("app", "Restart command accepted by Supervisor")
        else:
            write_event("error", "Supervisor did not accept restart command")

    threading.Thread(target=_restart_self_async, daemon=True).start()
    return jsonify({"ok": True, "accepted": True}), 202


@app.route("/api/apps")
def api_apps():
    """List all installed Home Assistant apps."""
    apps = list_installed_apps()
    return jsonify({"ok": True, "apps": apps})


@app.route("/api/app-health")
def api_app_health():
    """Check health of configured dependent apps."""
    config = get_app_config()
    dependent = config.get("dependent_apps", [])
    results = []
    for app_item in dependent:
        slug = app_item.get("slug", "")
        name = app_item.get("name", slug)
        if not slug:
            continue
        state = get_app_state(slug)
        results.append({"slug": slug, "name": name, "state": state})
    return jsonify({"ok": True, "apps": results})


@app.route("/api/app-restart", methods=["POST"])
def api_app_restart():
    """Restart a specific app by slug."""
    data = request.get_json(force=True)
    slug = data.get("slug", "").strip()
    if not slug:
        return jsonify({"ok": False, "error": "slug required"}), 400
    ok = restart_app(slug)
    return jsonify({"ok": ok})


@app.route("/api/dependent-apps", methods=["POST"])
def api_dependent_apps_save():
    """Save dependent apps selection to app config."""
    data = request.get_json(force=True)
    data, _ = normalize_dependent_apps_config(data)
    data, _ = normalize_notification_config(data)
    apps_list = data.get("dependent_apps", [])
    if not isinstance(apps_list, list):
        apps_list = []
    config, changed = normalize_dependent_apps_config(get_app_config())
    config, notif_changed = normalize_notification_config(config)
    changed = changed or notif_changed
    if changed:
        set_app_config(config)
    config["dependent_apps"] = apps_list
    resp = set_app_config(config)
    ok = resp.get("result") == "ok"
    write_event("config_change", f"Updated dependent apps: {len(apps_list)} selected")
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

    def _flush_latency_on_exit(*_args):
        _flush_latency_buffer(force=True)

    atexit.register(_flush_latency_on_exit)
    signal.signal(signal.SIGTERM, _flush_latency_on_exit)
    signal.signal(signal.SIGINT, _flush_latency_on_exit)

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
