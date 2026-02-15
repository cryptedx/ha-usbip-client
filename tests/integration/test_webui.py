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
    mocker.patch("usbip_lib.constants.EVENTS_FILE", events_file)
    mocker.patch("usbip_lib.events.EVENTS_FILE", events_file)

    # Also patch the EVENTS_FILE binding in app module (from-import creates a copy)
    import app as app_module

    mocker.patch.object(app_module, "EVENTS_FILE", events_file)

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

        assert 'href="/static/style.css?v=0.5.2-beta.2&t=' in html

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

    def test_dashboard_includes_system_diagnostics_panel(self, client):
        """Dashboard renders first-run diagnostics panel server-side."""
        resp = client.get("/")
        html = resp.get_data(as_text=True)

        assert 'id="dash-diagnostics"' in html

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
        assert "restartAddon" not in js

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
    def test_success(self, client, mock_usbip_env):
        resp = client.post(
            "/api/attach",
            json={"server": "192.168.1.44", "busid": "1-1.4", "name": "Test"},
        )
        data = resp.get_json()
        assert data["ok"] is True

    def test_missing_params(self, client):
        resp = client.post("/api/attach", json={"server": "192.168.1.44"})
        assert resp.status_code == 400

    def test_failure(self, client, mock_usbip_env):
        mock_usbip_env["subprocess"].return_value = pytest.importorskip(
            "unittest.mock"
        ).Mock(returncode=1, stdout="", stderr="connection refused")
        resp = client.post(
            "/api/attach",
            json={"server": "192.168.1.44", "busid": "1-1.4"},
        )
        data = resp.get_json()
        assert data["ok"] is False
        assert "Cannot reach USB/IP server" in data["detail"]


class TestApiDetach:
    def test_success(self, client, mock_usbip_env):
        resp = client.post("/api/detach", json={"port": 0})
        data = resp.get_json()
        assert data["ok"] is True

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


class TestApiConfig:
    def test_get(self, client):
        resp = client.get("/api/config")
        data = resp.get_json()
        assert data["ok"] is True
        assert "config" in data
        # New default should be present
        assert data["config"].get("log_auto_scroll") == "when_not_paused"

    def test_set(self, client, mock_usbip_env):
        resp = client.post("/api/config", json={"log_level": "debug"})
        data = resp.get_json()
        assert data["ok"] is True

    def test_set_auto_scroll(self, client, mock_usbip_env):
        resp = client.post("/api/config", json={"log_auto_scroll": "always"})
        data = resp.get_json()
        assert data["ok"] is True

    def test_get_migrates_legacy_dependent_key(self, client, mocker):
        expected_apps = [{"name": "Zigbee2MQTT", "slug": "45df7312_zigbee2mqtt"}]
        legacy_config = {
            "log_level": "info",
            "dependent_addons": expected_apps,
        }
        set_mock = mocker.patch("app.set_app_config", return_value={"result": "ok"})
        mocker.patch("app.get_app_config", return_value=legacy_config)

        resp = client.get("/api/config")
        data = resp.get_json()

        assert data["ok"] is True
        assert data["config"]["dependent_apps"] == expected_apps
        assert "dependent_addons" not in data["config"]
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

    def test_rejects_large_subnet(self, client):
        resp = client.post("/api/scan", json={"subnet": "192.168.0.0/16"})
        data = resp.get_json()
        assert data["ok"] is False

    def test_single_ip(self, client, mock_usbip_env):
        mock_usbip_env["subprocess"].return_value.stdout = SAMPLE_USBIP_LIST_OUTPUT
        resp = client.post("/api/scan", json={"subnet": "192.168.1.44"})
        data = resp.get_json()
        assert data["ok"] is True


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
