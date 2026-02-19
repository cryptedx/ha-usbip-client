"""Integration tests for the Flask WebUI API endpoints."""

import json
import os
import sys

import pytest

# Add the webui directory to path so we can import app
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "../../rootfs/usr/local/bin/webui")
)

from testdata import (
    SAMPLE_APP_CONFIG,
    SAMPLE_APP_INFO_RESPONSE_STARTED,
    SAMPLE_APP_INFO_RESPONSE_STOPPED,
    SAMPLE_APP_RESTART_RESPONSE,
    SAMPLE_APPS_LIST_RESPONSE,
    SAMPLE_DISCOVERY_DATA,
    SAMPLE_SUPERVISOR_INFO_RESPONSE,
    SAMPLE_USBIP_LIST_OUTPUT,
    SAMPLE_USBIP_PORT_OUTPUT,
)


@pytest.fixture
def mock_usbip_env(mocker, tmp_path):
    """Set up a fully mocked environment for the Flask app."""
    # Mock constants to use temp files
    events_file = str(tmp_path / "events.jsonl")
    latency_file = str(tmp_path / "latency_history.jsonl")
    mocker.patch("usbip_lib.constants.EVENTS_FILE", events_file)
    mocker.patch("usbip_lib.events.EVENTS_FILE", events_file)
    mocker.patch("usbip_lib.constants.LATENCY_HISTORY_FILE", latency_file)
    mocker.patch("usbip_lib.latency_history.LATENCY_HISTORY_FILE", latency_file)

    # Also patch the EVENTS_FILE binding in app module (from-import creates a copy)
    import app as app_module

    mocker.patch.object(app_module, "EVENTS_FILE", events_file)
    mocker.patch.object(app_module, "LATENCY_HISTORY_FILE", latency_file)

    # Mock supervisor API
    def _make_response(data):
        resp = mocker.Mock()
        resp.read.return_value = json.dumps(data).encode()
        resp.__enter__ = mocker.Mock(return_value=resp)
        resp.__exit__ = mocker.Mock(return_value=False)
        return resp

    mock_urlopen = mocker.patch("usbip_lib.config.urllib.request.urlopen")
    mock_urlopen.return_value = _make_response(SAMPLE_SUPERVISOR_INFO_RESPONSE)

    # Mock subprocess for usbip commands
    mock_run = mocker.patch("usbip_lib.usbip.subprocess.run")
    mock_run.return_value = mocker.Mock(returncode=0, stdout="", stderr="")

    return {
        "urlopen": mock_urlopen,
        "subprocess": mock_run,
        "events_file": events_file,
        "latency_file": latency_file,
    }


@pytest.fixture
def client(mock_usbip_env):
    """Create a Flask test client."""
    # We need to import app after mocking is set up
    from app import app

    # Fix template/static paths for testing (container paths don't exist locally)
    webui_dir = os.path.join(
        os.path.dirname(__file__), "..", "..", "rootfs", "usr", "local", "bin", "webui"
    )
    app.template_folder = os.path.abspath(os.path.join(webui_dir, "templates"))
    app.static_folder = os.path.abspath(os.path.join(webui_dir, "static"))
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


class TestIndexPage:
    def test_loads(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_stylesheet_uses_asset_stamp_cache_buster(self, client):
        """Rendered HTML includes style.css asset stamp for ingress cache busting."""
        resp = client.get("/")
        html = resp.get_data(as_text=True)

        import app as _app

        assert f'href="/static/style.css?v={_app.APP_VERSION}&t=' in html

    def test_internal_scroll_container_present(self, client):
        """Page renders internal scroll container for Ingress-consistent scrollbar ownership."""
        resp = client.get("/")
        html = resp.get_data(as_text=True)

        assert 'id="app-scroll"' in html
        assert 'id="app"' in html

    def test_toast_container_uses_live_region_attributes(self, client):
        """Toast container includes screen-reader live-region attributes."""
        resp = client.get("/")
        html = resp.get_data(as_text=True)

        assert 'id="toast-container"' in html
        assert 'role="status"' in html
        assert 'aria-live="polite"' in html
        assert 'aria-atomic="true"' in html

    def test_notification_config_controls_present(self, client):
        """Config tab renders notification preference controls."""
        resp = client.get("/")
        html = resp.get_data(as_text=True)

        assert 'id="cfg-notifications-enabled"' in html
        assert 'id="cfg-notif-type-device_lost"' in html
        assert 'id="cfg-notif-type-device_recovered"' in html
        assert 'id="cfg-notif-type-reattach_failed"' in html
        assert 'id="cfg-notif-type-flap_warning"' in html
        assert 'id="cfg-notif-type-flap_critical"' in html
        assert 'id="cfg-notif-type-app_down"' in html
        assert 'id="cfg-notif-type-app_restarted"' in html
        assert 'id="cfg-notif-type-app_restart_failed"' in html
        assert 'id="cfg-notif-type-device_attached"' in html
        assert 'id="cfg-notif-type-device_detached"' in html

    def test_dependent_apps_handlers_present(self, client):
        """Rendered HTML uses apps-only dependent app handlers and IDs."""
        resp = client.get("/")
        html = resp.get_data(as_text=True)

        assert 'id="dash-apps"' in html
        assert 'id="cfg-dependent-apps-list"' in html
        assert "loadAvailableApps()" in html
        assert "saveDependentApps()" in html
        assert "loadAvailableAddons" not in html
        assert "saveDependentAddons" not in html

    def test_config_reload_button_uses_forced_reload(self, client):
        """Config reload button triggers explicit forced reload handler."""
        resp = client.get("/")
        html = resp.get_data(as_text=True)

        assert 'onclick="loadConfig(true)"' in html

    def test_config_action_row_includes_restart_button(self, client):
        """Config action row exposes a visible restart button."""
        resp = client.get("/")
        html = resp.get_data(as_text=True)

        assert 'onclick="restartAddon()"' in html
        assert "↻ RESTART APP" in html

    def test_dashboard_includes_system_diagnostics_panel(self, client):
        """Dashboard renders first-run diagnostics panel server-side."""
        resp = client.get("/")
        html = resp.get_data(as_text=True)

        assert 'id="dash-diagnostics"' in html

    def test_dashboard_includes_latency_graph_container(self, client):
        """Dashboard renders server-latency graph container server-side."""
        resp = client.get("/")
        html = resp.get_data(as_text=True)

        assert 'id="dash-latency-graph"' in html

    def test_cookie_active_tab_renders_devices_as_active(self, client):
        """Initial active tab is rendered from cookie for full ingress reload compatibility."""
        client.set_cookie("usbip_active_tab", "devices")

        resp = client.get("/")
        html = resp.get_data(as_text=True)
        normalized_html = " ".join(html.split())

        assert 'data-tab="devices" href="?tab=devices"' in normalized_html
        assert normalized_html.count('class="tab active"') == 1
        assert 'id="tab-devices" class="tab-content active"' in normalized_html

    def test_invalid_cookie_active_tab_falls_back_to_dashboard(self, client):
        """Invalid tab cookies are ignored and dashboard remains default."""
        client.set_cookie("usbip_active_tab", "invalid-tab")

        resp = client.get("/")
        html = resp.get_data(as_text=True)
        normalized_html = " ".join(html.split())

        assert 'data-tab="dashboard" href="?tab=dashboard"' in normalized_html
        assert normalized_html.count('class="tab active"') == 1
        assert 'id="tab-dashboard" class="tab-content active"' in normalized_html

    def test_query_active_tab_overrides_cookie(self, client):
        """Query tab parameter has priority and is rendered server-side."""
        client.set_cookie("usbip_active_tab", "dashboard")

        resp = client.get("/?tab=devices")
        html = resp.get_data(as_text=True)
        normalized_html = " ".join(html.split())

        assert 'data-tab="devices" href="?tab=devices"' in normalized_html
        assert normalized_html.count('class="tab active"') == 1
        assert 'id="tab-devices" class="tab-content active"' in normalized_html

    def test_tab_navigation_links_exist_for_no_js_fallback(self, client):
        """Tabs are anchor links with ?tab fallback for ingress/no-JS resilience."""
        resp = client.get("/")
        html = resp.get_data(as_text=True)
        normalized_html = " ".join(html.split())

        assert 'data-tab="dashboard" href="?tab=dashboard"' in normalized_html
        assert 'data-tab="devices" href="?tab=devices"' in normalized_html
        assert 'data-tab="discovery" href="?tab=discovery"' in normalized_html
        assert 'data-tab="logs" href="?tab=logs"' in normalized_html
        assert 'data-tab="events" href="?tab=events"' in normalized_html
        assert 'data-tab="config" href="?tab=config"' in normalized_html

    def test_events_tab_renders_empty_state_server_side(self, client):
        """Events tab renders fallback content server-side on full reload."""
        resp = client.get("/?tab=events")
        html = resp.get_data(as_text=True)
        normalized_html = " ".join(html.split())

        assert resp.status_code == 200
        assert 'id="tab-events" class="tab-content active"' in normalized_html
        assert '<span class="dim">No events recorded</span>' in html

    def test_events_tab_renders_existing_events_server_side(
        self, client, mock_usbip_env
    ):
        """Events tab includes event entries server-side when events exist."""
        from usbip_lib.events import write_event

        write_event(
            "attach_ok",
            "attached",
            device="Printer",
            server="192.168.1.44",
            events_file=mock_usbip_env["events_file"],
        )

        resp = client.get("/?tab=events")
        html = resp.get_data(as_text=True)
        normalized_html = " ".join(html.split())

        assert resp.status_code == 200
        assert 'id="tab-events" class="tab-content active"' in normalized_html
        assert "event-type attach_ok" in html
        assert "attach_ok" in html
        assert "Printer" in html
        assert "192.168.1.44" in html
        assert "attached" in html

    def test_events_tab_renders_from_cookie(self, client, mock_usbip_env):
        """Cookie-only active tab should cause server-side events render."""
        from usbip_lib.events import write_event

        write_event(
            "attach_ok",
            "attached",
            device="Camera",
            server="10.0.0.2",
            events_file=mock_usbip_env["events_file"],
        )

        client.set_cookie("usbip_active_tab", "events")
        resp = client.get("/")
        html = resp.get_data(as_text=True)
        normalized_html = " ".join(html.split())

        assert resp.status_code == 200
        assert 'id="tab-events" class="tab-content active"' in normalized_html
        assert "Camera" in html

    def test_ingress_render_includes_critical_elements_and_prefixed_assets(
        self, client
    ):
        """Ingress render includes critical shell elements and ingress-prefixed assets."""
        ingress_path = "/api/hassio_ingress/abc123"
        resp = client.get("/", headers={"X-Ingress-Path": ingress_path})
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert f'href="{ingress_path}/static/style.css?v=' in html
        assert 'id="app-scroll"' in html
        assert 'id="header"' in html
        assert 'id="tabs"' in html
        assert 'id="tab-dashboard"' in html
        assert 'id="tab-devices"' in html
        assert 'id="tab-logs"' in html

    def test_events_order_newest_first(self, client, mock_usbip_env):
        """Server-rendered events should appear newest-first in HTML."""
        import json
        from datetime import datetime, timezone, timedelta

        # write two events with explicit timestamps (older, then newer)
        events_file = mock_usbip_env["events_file"]
        older = {
            "ts": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
            "type": "evt_old",
            "device": "OldDev",
            "server": "1.1.1.1",
            "detail": "first",
        }
        newer = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": "evt_new",
            "device": "NewDev",
            "server": "2.2.2.2",
            "detail": "second",
        }
        with open(events_file, "w") as f:
            f.write(json.dumps(older) + "\n")
            f.write(json.dumps(newer) + "\n")

        resp = client.get("/?tab=events")
        html = resp.get_data(as_text=True)

        # newer should appear before older
        assert html.index("NewDev") < html.index("OldDev")

    def test_events_cleared_reflected_server_side(self, client, mock_usbip_env):
        """Clearing events via API removes them from subsequent server-rendered pages."""
        from usbip_lib.events import write_event

        write_event(
            "x", "y", device="D", server="S", events_file=mock_usbip_env["events_file"]
        )
        resp = client.post("/api/events/clear")
        assert resp.get_json()["ok"] is True

        resp = client.get("/?tab=events")
        html = resp.get_data(as_text=True)
        assert '<span class="dim">No events recorded</span>' in html

    def test_api_events_returns_written_events(self, client, mock_usbip_env):
        """/api/events should return events written by write_event."""
        from usbip_lib.events import write_event

        write_event(
            "t1",
            "d1",
            device="Dev1",
            server="S1",
            events_file=mock_usbip_env["events_file"],
        )
        resp = client.get("/api/events")
        data = resp.get_json()
        assert data["ok"] is True
        assert isinstance(data.get("events"), list)
        assert any(e.get("device") == "Dev1" for e in data["events"])

    def test_server_side_escapes_event_fields(self, client, mock_usbip_env):
        """Server-rendered event fields must be HTML-escaped to avoid XSS."""
        import json

        events_file = mock_usbip_env["events_file"]
        payload = {
            "ts": "2020-01-01T00:00:00Z",
            "type": "t",
            "device": "<b>Bad</b>",
            "server": "S",
            "detail": "<script>alert(1)</script>",
        }
        with open(events_file, "w") as f:
            f.write(json.dumps(payload) + "\n")

        resp = client.get("/?tab=events")
        html = resp.get_data(as_text=True)

        # Raw script tag must not be present; escaped form should appear
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


class TestStaticAppJsCompatibility:
    def test_exposes_app_handlers_on_window_only(self, client):
        """Served app.js exposes current dependent-app functions without legacy aliases."""
        resp = client.get("/static/app.js")
        assert resp.status_code == 200
        js = resp.get_data(as_text=True)

        assert "function loadAvailableApps()" in js
        assert "function saveDependentApps()" in js
        assert "window.loadAvailableApps = loadAvailableApps;" in js
        assert "window.saveDependentApps = saveDependentApps;" in js
        assert "loadAvailableAddons" not in js
        assert "saveDependentAddons" not in js
        assert "restartAddon" in js

    def test_persists_active_tab_via_cookie(self, client):
        """Tab persistence uses cookie for server-side rendering in Ingress."""
        resp = client.get("/static/app.js")
        assert resp.status_code == 200
        js = resp.get_data(as_text=True)

        assert "const ACTIVE_TAB_COOKIE_KEY = 'usbip_active_tab';" in js
        assert (
            "document.cookie = `${ACTIVE_TAB_COOKIE_KEY}=${encodeURIComponent(tab)}; Path=/; SameSite=Lax`;"
            in js
        )
        assert "event.preventDefault()" in js

    def test_restart_uses_ingress_safe_two_step_confirmation(self, client):
        """Restart flow uses two-step confirmation instead of browser confirm dialog."""
        resp = client.get("/static/app.js")
        assert resp.status_code == 200
        js = resp.get_data(as_text=True)

        assert "Click RESTART APP again within 10 seconds to confirm." in js
        assert "⚠ CLICK AGAIN TO RESTART" in js
        assert "confirm(" not in js

    def test_dependent_app_restart_shows_toast_feedback(self, client):
        """Dependent app restart flow shows immediate and result toasts for user feedback."""
        resp = client.get("/static/app.js")
        assert resp.status_code == 200
        js = resp.get_data(as_text=True)

        assert "Restarting ${name}..." in js
        assert "${name} restarted" in js
        assert "Restart failed: ${detail}" in js

    def test_dependent_app_restart_disables_button_while_running(self, client):
        """Dependent app restart button is disabled during in-flight request to prevent double click."""
        resp = client.get("/static/app.js")
        assert resp.status_code == 200
        js = resp.get_data(as_text=True)

        assert "onclick=\"restartApp('${esc(a.slug)}','${esc(a.name)}', this)\"" in js
        assert "async function restartApp(slug, name, buttonEl = null)" in js
        assert "buttonEl.disabled = true;" in js
        assert "buttonEl.textContent = 'RESTARTING...';" in js

    def test_initial_load_hydrates_active_tab_data(self, client):
        """Initial page load hydrates currently active tab data (ingress/full reload safe)."""
        resp = client.get("/static/app.js")
        assert resp.status_code == 200
        js = resp.get_data(as_text=True)

        assert "const loadTabData = (tab) => {" in js
        assert (
            "const activeButton = tabs.find(btn => btn.classList.contains('active'));"
            in js
        )
        assert "if (activeButton) {" in js
        assert "loadTabData(activeButton.dataset.tab);" in js
        assert "else if (tab === 'events') refreshEvents();" in js

    def test_dashboard_js_includes_latency_graph_renderer(self, client):
        """Served app.js includes dashboard latency graph renderer hooks."""
        resp = client.get("/static/app.js")
        assert resp.status_code == 200
        js = resp.get_data(as_text=True)

        assert "function renderLatencyGraph(history)" in js
        assert "document.getElementById('dash-latency-graph')" in js
        assert "Latency over the last hour" in js
        assert "-45m" in js
        assert "-15m" in js


class TestStaticCssCompatibility:
    def test_served_stylesheet_includes_custom_vertical_scrollbar(self, client):
        """Served style.css includes themed custom vertical scrollbar rules."""
        resp = client.get("/static/style.css")
        assert resp.status_code == 200
        css = resp.get_data(as_text=True)

        assert "--scrollbar-size: 12px;" in css
        assert "scrollbar-color: var(--scrollbar-thumb) var(--scrollbar-track);" in css
        assert "#app-scroll {" in css
        assert "#app-scroll::-webkit-scrollbar" in css
        assert "#app-scroll *::-webkit-scrollbar-thumb:hover" in css

    def test_served_stylesheet_includes_latency_graph_styles(self, client):
        """Served style.css includes dashboard latency graph classes."""
        resp = client.get("/static/style.css")
        assert resp.status_code == 200
        css = resp.get_data(as_text=True)

        assert ".latency-graph-wrap" in css
        assert ".latency-graph" in css
        assert ".latency-legend" in css


class TestApiStatus:
    def test_returns_json(self, client, mock_usbip_env):
        mock_usbip_env["subprocess"].return_value.stdout = SAMPLE_USBIP_PORT_OUTPUT
        mock_usbip_env["subprocess"].return_value.returncode = 0
        resp = client.get("/api/status")
        data = resp.get_json()
        assert data["ok"] is True
        assert "devices" in data

    def test_empty_when_no_devices(self, client, mock_usbip_env):
        mock_usbip_env["subprocess"].return_value.stdout = ""
        mock_usbip_env["subprocess"].return_value.returncode = 1
        resp = client.get("/api/status")
        data = resp.get_json()
        assert data["ok"] is True
        assert data["devices"] == []

    def test_includes_flapping_warning_state(self, client, mock_usbip_env):
        from usbip_lib.events import write_event

        write_event(
            "flap_warning",
            "unstable",
            device="Z-Wave Stick",
            server="192.168.1.44",
            data={
                "device_key": "192.168.1.44:1-1.4",
                "count": 3,
                "window_seconds": 600,
                "level": "warning",
            },
            events_file=mock_usbip_env["events_file"],
        )

        resp = client.get("/api/status")
        data = resp.get_json()

        assert data["ok"] is True
        assert data["warnings"]["flapping"]["total"] == 1
        assert data["warnings"]["flapping"]["highest_level"] == "warning"
        assert data["warnings"]["flapping"]["devices"][0]["device"] == "Z-Wave Stick"


class TestApiDiscover:
    def test_requires_server(self, client):
        resp = client.get("/api/discover")
        assert resp.status_code == 400

    def test_returns_devices(self, client, mock_usbip_env):
        mock_usbip_env["subprocess"].return_value.stdout = SAMPLE_USBIP_LIST_OUTPUT
        resp = client.get("/api/discover?server=192.168.1.44")
        data = resp.get_json()
        assert data["ok"] is True
        assert len(data["devices"]) == 2


class TestApiAttach:
    def test_success(self, client, mocker):
        attach_mock = mocker.patch("app.attach_device", return_value=True)
        resp = client.post(
            "/api/attach",
            json={"server": "192.168.1.44", "busid": "1-1.4", "name": "Test"},
        )
        data = resp.get_json()
        assert data["ok"] is True
        attach_mock.assert_called_once_with(
            server="192.168.1.44", bus_id="1-1.4", device_name="Test"
        )

    def test_missing_params(self, client):
        resp = client.post("/api/attach", json={"server": "192.168.1.44"})
        assert resp.status_code == 400

    def test_failure(self, client, mocker):
        mocker.patch("app.attach_device", return_value=False)
        resp = client.post(
            "/api/attach",
            json={"server": "192.168.1.44", "busid": "1-1.4"},
        )
        data = resp.get_json()
        assert data["ok"] is False
        assert "Operation failed" in data["detail"]


class TestApiDetach:
    def test_success(self, client, mocker):
        detach_mock = mocker.patch("app.detach_device", return_value=True)
        resp = client.post("/api/detach", json={"port": 0})
        data = resp.get_json()
        assert data["ok"] is True
        detach_mock.assert_called_once_with("0")

    def test_missing_port(self, client):
        resp = client.post("/api/detach", json={})
        assert resp.status_code == 400


class TestApiDetachAll:
    def test_success(self, client, mock_usbip_env):
        mock_usbip_env["subprocess"].return_value.stdout = SAMPLE_USBIP_PORT_OUTPUT
        resp = client.post("/api/detach-all")
        data = resp.get_json()
        assert data["ok"] is True
        assert "detached" in data
        assert "failed" in data


class TestApiAttachAll:
    def test_mixed_outcomes_with_device_id_resolution(self, client, mocker):
        mocker.patch(
            "app.get_app_config",
            return_value={
                "usbipd_server_address": "192.168.1.44",
                "devices": [
                    {"name": "Resolved OK", "device_or_bus_id": "0658:0200"},
                    {"name": "Missing ID", "device_or_bus_id": "ffff:ffff"},
                    {"name": "Direct Bus Fails", "device_or_bus_id": "1-1.3"},
                ],
            },
        )
        parse_mock = mocker.patch(
            "app.parse_usbip_list", return_value=SAMPLE_DISCOVERY_DATA
        )

        def _run_cmd_side_effect(cmd, timeout=15):
            if "attach" in cmd:
                if "1-1.4" in cmd:
                    return (0, "attached", "")
                if "1-1.3" in cmd:
                    return (1, "", "connection refused")
            return (0, "", "")

        mocker.patch("app.run_cmd", side_effect=_run_cmd_side_effect)

        resp = client.post("/api/attach-all")
        data = resp.get_json()

        assert data["ok"] is True
        assert len(data["results"]) == 3
        assert data["results"][0] == {
            "name": "Resolved OK",
            "ok": True,
            "detail": "attached",
        }
        assert data["results"][1] == {
            "name": "Missing ID",
            "ok": False,
            "detail": "device ffff:ffff not found on 192.168.1.44",
        }
        assert data["results"][2]["name"] == "Direct Bus Fails"
        assert data["results"][2]["ok"] is False
        assert "Cannot reach USB/IP server 192.168.1.44" in data["results"][2]["detail"]

        parse_mock.assert_called_once_with("192.168.1.44")

        events_resp = client.get("/api/events")
        events = events_resp.get_json()["events"]
        attach_events = [
            e for e in events if e.get("type") in {"attach_ok", "attach_fail"}
        ]
        assert len(attach_events) == 2
        assert any(
            e.get("type") == "attach_ok" and e.get("device") == "Resolved OK"
            for e in attach_events
        )
        assert any(
            e.get("type") == "attach_fail" and e.get("device") == "Direct Bus Fails"
            for e in attach_events
        )


class TestApiConfig:
    def test_get(self, client):
        resp = client.get("/api/config")
        data = resp.get_json()
        assert data["ok"] is True
        assert "config" in data
        # New default should be present
        assert data["config"].get("log_auto_scroll") == "when_not_paused"
        assert data["config"].get("notifications_enabled") is True
        assert "device_lost" in data["config"].get("notification_types", [])

    def test_set(self, client, mock_usbip_env):
        resp = client.post("/api/config", json={"log_level": "debug"})
        data = resp.get_json()
        assert data["ok"] is True

    def test_backup_returns_current_config_shape(self, client):
        resp = client.get("/api/config/backup")
        data = resp.get_json()

        assert isinstance(data, dict)
        assert data.get("log_auto_scroll") == "when_not_paused"
        assert data.get("notifications_enabled") is True
        assert isinstance(data.get("dependent_apps"), list)

    def test_restore_normalizes_legacy_payload_and_writes_event(self, client, mocker):
        set_mock = mocker.patch("app.set_app_config", return_value={"result": "ok"})

        resp = client.post(
            "/api/config/restore",
            json={
                "log_level": "debug",
                "dependent_addons": [{"name": "Z2M", "slug": "z2m"}],
                "notifications_enabled": "yes",
                "notification_types": ["device_lost", "invalid", 123, "device_lost"],
            },
        )
        data = resp.get_json()

        assert data["ok"] is True
        saved = set_mock.call_args.args[0]
        assert saved["dependent_apps"] == [{"name": "Z2M", "slug": "z2m"}]
        assert "dependent_addons" not in saved
        assert saved["notifications_enabled"] is True
        assert saved["notification_types"] == ["device_lost"]

        events_resp = client.get("/api/events")
        events = events_resp.get_json()["events"]
        assert any(e.get("type") == "config_restore" for e in events)

    def test_set_returns_supervisor_error_payload(self, client, mocker):
        mocker.patch(
            "app.set_app_config",
            return_value={"result": "error", "message": "write failed"},
        )

        resp = client.post("/api/config", json={"log_level": "debug"})
        data = resp.get_json()

        assert data["ok"] is False
        assert data["response"]["result"] == "error"
        assert data["response"]["message"] == "write failed"

    def test_set_writes_config_change_event(self, client):
        resp = client.post("/api/config", json={"log_level": "debug"})
        data = resp.get_json()
        assert data["ok"] is True

        events_resp = client.get("/api/events")
        events = events_resp.get_json()["events"]
        config_events = [e for e in events if e.get("type") == "config_change"]
        assert config_events
        assert '"log_level": "debug"' in config_events[-1].get("detail", "")

    def test_set_auto_scroll(self, client, mock_usbip_env):
        resp = client.post("/api/config", json={"log_auto_scroll": "always"})
        data = resp.get_json()
        assert data["ok"] is True

    def test_get_migrates_legacy_dependent_key(self, client, mocker):
        expected_apps = [{"name": "Zigbee2MQTT", "slug": "45df7312_zigbee2mqtt"}]
        normalized_config = {
            "log_level": "info",
            "dependent_apps": expected_apps,
        }
        set_mock = mocker.patch("app.set_app_config", return_value={"result": "ok"})
        mocker.patch("app.get_app_config", return_value=normalized_config)

        resp = client.get("/api/config")
        data = resp.get_json()

        assert data["ok"] is True
        assert data["config"]["dependent_apps"] == expected_apps
        set_mock.assert_not_called()

    def test_set_accepts_legacy_dependent_key_payload(self, client, mocker):
        set_mock = mocker.patch("app.set_app_config", return_value={"result": "ok"})

        resp = client.post(
            "/api/config",
            json={
                "log_level": "debug",
                "dependent_addons": [{"name": "Z-Wave JS", "slug": "core_zwave_js"}],
            },
        )
        data = resp.get_json()

        assert data["ok"] is True
        payload = set_mock.call_args.args[0]
        assert payload["dependent_apps"] == [
            {"name": "Z-Wave JS", "slug": "core_zwave_js"}
        ]
        assert "dependent_addons" not in payload

    def test_set_persists_notification_preferences(self, client, mocker):
        set_mock = mocker.patch("app.set_app_config", return_value={"result": "ok"})
        mocker.patch(
            "app.get_app_config",
            return_value={
                "notifications_enabled": True,
                "notification_types": ["device_lost", "app_down"],
            },
        )

        resp = client.post(
            "/api/config",
            json={
                "log_level": "debug",
                "notifications_enabled": True,
                "notification_types": ["device_lost", "app_down"],
            },
        )
        data = resp.get_json()

        assert data["ok"] is True
        payload = set_mock.call_args.args[0]
        assert payload["notifications_enabled"] is True
        assert payload["notification_types"] == ["device_lost", "app_down"]

    def test_set_reports_notification_persist_mismatch(self, client, mocker):
        mocker.patch("app.set_app_config", return_value={"result": "ok"})
        mocker.patch(
            "app.get_app_config",
            return_value={
                "notifications_enabled": True,
                "notification_types": [
                    "device_lost",
                    "device_recovered",
                    "reattach_failed",
                    "flap_warning",
                    "flap_critical",
                    "app_down",
                    "app_restarted",
                    "app_restart_failed",
                    "device_attached",
                    "device_detached",
                ],
            },
        )

        resp = client.post(
            "/api/config",
            json={
                "log_level": "debug",
                "notifications_enabled": True,
                "notification_types": ["device_lost", "app_down"],
            },
        )
        data = resp.get_json()

        assert data["ok"] is False
        assert "not persisted" in data["detail"].lower()


class TestApiEvents:
    def test_empty(self, client):
        resp = client.get("/api/events")
        data = resp.get_json()
        assert data["ok"] is True
        assert data["events"] == []

    def test_clear(self, client, mock_usbip_env):
        # Write an event first
        from usbip_lib.events import write_event

        write_event("test", "data", events_file=mock_usbip_env["events_file"])

        resp = client.post("/api/events/clear")
        assert resp.get_json()["ok"] is True


class TestApiCachingHeaders:
    def test_api_responses_are_no_store(self, client):
        resp = client.get("/api/config")
        assert resp.status_code == 200
        assert "no-store" in resp.headers.get("Cache-Control", "")
        assert resp.headers.get("Pragma") == "no-cache"
        assert resp.headers.get("Expires") == "0"

    def test_non_api_response_keeps_default_cache_headers(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "no-store" in resp.headers.get("Cache-Control", "")


class TestApiHealth:
    def test_returns_servers(self, client):
        resp = client.get("/api/health")
        data = resp.get_json()
        assert data["ok"] is True
        assert "servers" in data
        assert "history" in data
        assert "timestamps" in data["history"]
        assert "series" in data["history"]

    def test_includes_pending_latency_buffer_samples(self, client):
        import app as app_module

        with app_module.health_lock:
            app_module.health_state.clear()
            app_module.health_state.update(
                {
                    "192.168.1.44": {
                        "online": True,
                        "latency_ms": 1.2,
                        "last_check": "2026-02-17T10:00:00Z",
                    }
                }
            )
        with app_module.latency_lock:
            app_module.latency_buffer.clear()
            app_module.latency_buffer.extend(
                [
                    {
                        "ts": "2026-02-17T10:00:30Z",
                        "servers": {"192.168.1.44": 1.3},
                    },
                    {
                        "ts": "2026-02-17T10:01:00Z",
                        "servers": {"192.168.1.44": 1.4},
                    },
                ]
            )

        resp = client.get("/api/health")
        data = resp.get_json()

        assert data["ok"] is True
        assert len(data["history"]["timestamps"]) >= 2
        series = data["history"]["series"].get("192.168.1.44", [])
        assert any(v == 1.3 for v in series)
        assert any(v == 1.4 for v in series)


class TestApiDiagnostics:
    def test_returns_expected_checks(self, client, mocker):
        mocker.patch("app.os.path.exists", return_value=True)
        mocker.patch("app.run_cmd", return_value=(0, "/usr/sbin/usbip", ""))
        mocker.patch("app.ping_server", return_value=4.2)
        mocker.patch("app.parse_usbip_list", return_value=[{"busid": "1-1.4"}])

        resp = client.get("/api/diagnostics")
        data = resp.get_json()

        assert data["ok"] is True
        assert data["checks"]["vhci_module_loaded"] is True
        assert data["checks"]["usbip_command_available"] is True
        assert data["checks"]["default_server_configured"] is True
        assert data["checks"]["default_server_reachable"] is True
        assert data["checks"]["discoverable_devices"] == 1

    def test_without_configured_server(self, client, mocker):
        mocker.patch("app.get_app_config", return_value={"devices": []})
        mocker.patch("app.os.path.exists", return_value=False)
        mocker.patch("app.run_cmd", return_value=(1, "", "not found"))

        resp = client.get("/api/diagnostics")
        data = resp.get_json()

        assert data["ok"] is True
        assert data["default_server"] == ""
        assert data["checks"]["default_server_configured"] is False
        assert data["checks"]["default_server_reachable"] is None


class TestApiScan:
    def test_requires_subnet(self, client):
        resp = client.post("/api/scan", json={})
        assert resp.status_code == 400

    def test_rejects_invalid_subnet_format(self, client):
        resp = client.post("/api/scan", json={"subnet": "192.168.1"})
        data = resp.get_json()

        assert resp.status_code == 400
        assert data["ok"] is False
        assert "Invalid subnet format" in data["error"]

    def test_rejects_large_subnet(self, client):
        resp = client.post("/api/scan", json={"subnet": "192.168.0.0/16"})
        data = resp.get_json()
        assert data["ok"] is False

    def test_rejects_23_subnet_for_safety(self, client):
        resp = client.post("/api/scan", json={"subnet": "192.168.0.0/23"})
        data = resp.get_json()

        assert resp.status_code == 400
        assert data["ok"] is False
        assert "Minimum /24 subnet for safety" in data["error"]

    def test_single_ip(self, client, mock_usbip_env):
        mock_usbip_env["subprocess"].return_value.stdout = SAMPLE_USBIP_LIST_OUTPUT
        resp = client.post("/api/scan", json={"subnet": "192.168.1.44"})
        data = resp.get_json()
        assert data["ok"] is True

    def test_subnet_scan_asserts_results_by_count_and_set(self, client, mocker):
        online_hosts = {"192.168.1.10", "192.168.1.44"}

        def _ping_side_effect(ip, timeout=1.5):
            return 4.2 if ip in online_hosts else None

        def _discover_side_effect(ip):
            return [
                {
                    "server": ip,
                    "busid": "1-1.4",
                    "name": "Sample Device",
                    "device_id": "0658:0200",
                }
            ]

        mocker.patch("app.ping_server", side_effect=_ping_side_effect)
        mocker.patch("app.parse_usbip_list", side_effect=_discover_side_effect)

        resp = client.post("/api/scan", json={"subnet": "192.168.1.0/24"})
        data = resp.get_json()

        assert resp.status_code == 200
        assert data["ok"] is True
        assert len(data["servers"]) == 2
        discovered_hosts = {entry["server"] for entry in data["servers"]}
        assert discovered_hosts == online_hosts
        assert all(isinstance(entry.get("devices"), list) for entry in data["servers"])

    def test_subnet_scan_limits_probes_to_254_hosts(self, client, mocker):
        ping_mock = mocker.patch("app.ping_server", return_value=None)
        discover_mock = mocker.patch("app.parse_usbip_list")

        resp = client.post("/api/scan", json={"subnet": "192.168.1.0/24"})
        data = resp.get_json()

        assert resp.status_code == 200
        assert data["ok"] is True
        assert data["servers"] == []
        assert ping_mock.call_count == 254
        discover_mock.assert_not_called()

    def test_scan_writes_event_with_found_server_count(self, client, mocker):
        mocker.patch("app.ping_server", return_value=3.7)
        mocker.patch(
            "app.parse_usbip_list",
            return_value=[
                {
                    "server": "192.168.1.44",
                    "busid": "1-1.4",
                    "name": "Sample Device",
                    "device_id": "0658:0200",
                }
            ],
        )

        resp = client.post("/api/scan", json={"subnet": "192.168.1.44"})
        data = resp.get_json()

        assert resp.status_code == 200
        assert data["ok"] is True
        assert len(data["servers"]) == 1

        events_resp = client.get("/api/events")
        events = events_resp.get_json()["events"]
        scan_events = [event for event in events if event.get("type") == "scan"]
        assert scan_events
        assert (
            scan_events[-1].get("detail") == "Scanned 192.168.1.44, found 1 server(s)"
        )

    def test_scan_writes_event_with_zero_found_servers(self, client, mocker):
        mocker.patch("app.ping_server", return_value=None)
        parse_mock = mocker.patch("app.parse_usbip_list")

        resp = client.post("/api/scan", json={"subnet": "192.168.1.44"})
        data = resp.get_json()

        assert resp.status_code == 200
        assert data["ok"] is True
        assert data["servers"] == []
        parse_mock.assert_not_called()

        events_resp = client.get("/api/events")
        events = events_resp.get_json()["events"]
        scan_events = [event for event in events if event.get("type") == "scan"]
        assert scan_events
        assert (
            scan_events[-1].get("detail") == "Scanned 192.168.1.44, found 0 server(s)"
        )


class TestApiUsbDb:
    def test_lookup(self, client):
        resp = client.get("/api/usb-db?id=0658:0200")
        data = resp.get_json()
        assert data["ok"] is True
        assert data["id"] == "0658:0200"


class TestApiLogs:
    def test_returns_lines(self, client):
        resp = client.get("/api/logs")
        data = resp.get_json()
        assert data["ok"] is True
        assert "lines" in data

    def test_falls_back_to_direct_fetch_and_filters_by_level(self, client, mocker):
        mocker.patch("app.log_buffer", [])
        fetch_mock = mocker.patch(
            "app._fetch_logs_direct",
            return_value=[
                "INFO startup complete",
                "ERROR attach failed",
                "warning reconnecting",
                "error retry exceeded",
            ],
        )

        resp = client.get("/api/logs?level=error")
        data = resp.get_json()

        assert data["ok"] is True
        assert data["lines"] == ["ERROR attach failed", "error retry exceeded"]
        fetch_mock.assert_called_once()


# ---------------------------------------------------------------------------
# App management endpoint tests
# ---------------------------------------------------------------------------


class TestApiApps:
    def test_returns_app_list(self, client, mock_usbip_env):
        """GET /api/apps should return all installed apps."""

        # Override the urlopen mock to return apps list for the endpoint
        def _make_response(data):
            import unittest.mock as um

            resp = um.Mock()
            resp.read.return_value = json.dumps(data).encode()
            resp.__enter__ = um.Mock(return_value=resp)
            resp.__exit__ = um.Mock(return_value=False)
            return resp

        mock_usbip_env["urlopen"].return_value = _make_response(
            SAMPLE_APPS_LIST_RESPONSE
        )

        resp = client.get("/api/apps")
        data = resp.get_json()
        assert data["ok"] is True
        assert "apps" in data
        assert "addons" not in data
        assert len(data["apps"]) == 4
        slugs = [a["slug"] for a in data["apps"]]
        assert "45df7312_zigbee2mqtt" in slugs

    def test_legacy_apps_route_removed(self, client):
        resp = client.get("/api/addons")
        assert resp.status_code == 404

    def test_apps_api_error(self, client, mock_usbip_env):
        """GET /api/apps should return empty list on API error."""
        import unittest.mock as um

        resp_mock = um.Mock()
        resp_mock.read.return_value = json.dumps({"result": "error"}).encode()
        resp_mock.__enter__ = um.Mock(return_value=resp_mock)
        resp_mock.__exit__ = um.Mock(return_value=False)
        mock_usbip_env["urlopen"].return_value = resp_mock

        resp = client.get("/api/apps")
        data = resp.get_json()
        assert data["ok"] is True
        assert data["apps"] == []


class TestApiAppHealth:
    def test_no_dependent_apps(self, client, mock_usbip_env):
        """GET /api/app-health with no dependents configured."""
        resp = client.get("/api/app-health")
        data = resp.get_json()
        assert data["ok"] is True
        assert data["apps"] == []
        assert "addons" not in data

    def test_with_dependent_apps(self, client, mock_usbip_env):
        """GET /api/app-health with dependents configured."""
        import unittest.mock as um

        # First call returns config with dependent_apps, second returns app info
        config_with_deps = dict(SAMPLE_APP_CONFIG)
        config_with_deps["dependent_apps"] = [
            {"name": "Zigbee2MQTT", "slug": "45df7312_zigbee2mqtt"},
        ]
        config_resp = {"result": "ok", "data": {"options": config_with_deps}}

        def _make_response(data):
            resp = um.Mock()
            resp.read.return_value = json.dumps(data).encode()
            resp.__enter__ = um.Mock(return_value=resp)
            resp.__exit__ = um.Mock(return_value=False)
            return resp

        # urlopen is called twice: once for config, once for app info
        mock_usbip_env["urlopen"].side_effect = [
            _make_response(config_resp),
            _make_response(SAMPLE_APP_INFO_RESPONSE_STARTED),
        ]

        resp = client.get("/api/app-health")
        data = resp.get_json()
        assert data["ok"] is True
        assert len(data["apps"]) == 1
        assert data["apps"][0]["state"] == "started"
        assert data["apps"][0]["slug"] == "45df7312_zigbee2mqtt"

    def test_legacy_app_health_route_removed(self, client):
        resp = client.get("/api/addon-health")
        assert resp.status_code == 404


class TestApiAppRestart:
    def test_requires_slug(self, client):
        """POST /api/app-restart without slug returns 400."""
        resp = client.post("/api/app-restart", json={})
        assert resp.status_code == 400

    def test_restart_success(self, client, mock_usbip_env):
        """POST /api/app-restart with valid slug."""
        import unittest.mock as um

        resp_mock = um.Mock()
        resp_mock.read.return_value = json.dumps(SAMPLE_APP_RESTART_RESPONSE).encode()
        resp_mock.__enter__ = um.Mock(return_value=resp_mock)
        resp_mock.__exit__ = um.Mock(return_value=False)
        mock_usbip_env["urlopen"].return_value = resp_mock

        resp = client.post("/api/app-restart", json={"slug": "45df7312_zigbee2mqtt"})
        data = resp.get_json()
        assert data["ok"] is True

    def test_legacy_app_restart_route_removed(self, client):
        resp = client.post("/api/addon-restart", json={"slug": "45df7312_zigbee2mqtt"})
        assert resp.status_code == 404


class TestApiDependentAppsSave:
    def test_save_selection(self, client, mock_usbip_env):
        """POST /api/dependent-apps saves selection."""
        apps_to_save = [
            {"name": "Zigbee2MQTT", "slug": "45df7312_zigbee2mqtt"},
            {"name": "Z-Wave JS", "slug": "core_zwave_js"},
        ]
        resp = client.post(
            "/api/dependent-apps",
            json={"dependent_apps": apps_to_save},
        )
        data = resp.get_json()
        assert data["ok"] is True

    def test_save_empty_selection(self, client, mock_usbip_env):
        """POST /api/dependent-apps with empty list."""
        resp = client.post(
            "/api/dependent-apps",
            json={"dependent_apps": []},
        )
        data = resp.get_json()
        assert data["ok"] is True

    def test_legacy_dependent_route_removed(self, client):
        resp = client.post(
            "/api/dependent-addons",
            json={"dependent_apps": []},
        )
        assert resp.status_code == 404


class TestSystemRestart:
    def test_restart_returns_accepted_response(self, client, mocker):
        """POST /api/system/restart should respond accepted immediately."""
        thread_mock = mocker.Mock()
        thread_cls = mocker.patch("app.threading.Thread", return_value=thread_mock)

        resp = client.post("/api/system/restart")

        assert resp.status_code == 202
        assert resp.get_json() == {"ok": True, "accepted": True}
        thread_cls.assert_called_once()
        thread_mock.start.assert_called_once()
