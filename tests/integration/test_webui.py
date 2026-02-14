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
    SAMPLE_ADDON_CONFIG,
    SAMPLE_ADDON_INFO_RESPONSE_STARTED,
    SAMPLE_ADDON_INFO_RESPONSE_STOPPED,
    SAMPLE_ADDON_RESTART_RESPONSE,
    SAMPLE_ADDONS_LIST_RESPONSE,
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


class TestApiHealth:
    def test_returns_servers(self, client):
        resp = client.get("/api/health")
        data = resp.get_json()
        assert data["ok"] is True
        assert "servers" in data


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
# Add-on management endpoint tests
# ---------------------------------------------------------------------------


class TestApiAddons:
    def test_returns_addon_list(self, client, mock_usbip_env):
        """GET /api/addons should return all installed add-ons."""

        # Override the urlopen mock to return addons list for the addons endpoint
        def _make_response(data):
            import unittest.mock as um

            resp = um.Mock()
            resp.read.return_value = json.dumps(data).encode()
            resp.__enter__ = um.Mock(return_value=resp)
            resp.__exit__ = um.Mock(return_value=False)
            return resp

        mock_usbip_env["urlopen"].return_value = _make_response(
            SAMPLE_ADDONS_LIST_RESPONSE
        )

        resp = client.get("/api/addons")
        data = resp.get_json()
        assert data["ok"] is True
        assert "addons" in data
        assert len(data["addons"]) == 4
        slugs = [a["slug"] for a in data["addons"]]
        assert "45df7312_zigbee2mqtt" in slugs

    def test_addons_api_error(self, client, mock_usbip_env):
        """GET /api/addons should return empty list on API error."""
        import unittest.mock as um

        resp_mock = um.Mock()
        resp_mock.read.return_value = json.dumps({"result": "error"}).encode()
        resp_mock.__enter__ = um.Mock(return_value=resp_mock)
        resp_mock.__exit__ = um.Mock(return_value=False)
        mock_usbip_env["urlopen"].return_value = resp_mock

        resp = client.get("/api/addons")
        data = resp.get_json()
        assert data["ok"] is True
        assert data["addons"] == []


class TestApiAddonHealth:
    def test_no_dependent_addons(self, client, mock_usbip_env):
        """GET /api/addon-health with no dependents configured."""
        resp = client.get("/api/addon-health")
        data = resp.get_json()
        assert data["ok"] is True
        assert data["addons"] == []

    def test_with_dependent_addons(self, client, mock_usbip_env):
        """GET /api/addon-health with dependents configured."""
        import unittest.mock as um

        # First call returns config with dependent_addons, second returns addon info
        config_with_deps = dict(SAMPLE_ADDON_CONFIG)
        config_with_deps["dependent_addons"] = [
            {"name": "Zigbee2MQTT", "slug": "45df7312_zigbee2mqtt"},
        ]
        config_resp = {"result": "ok", "data": {"options": config_with_deps}}

        def _make_response(data):
            resp = um.Mock()
            resp.read.return_value = json.dumps(data).encode()
            resp.__enter__ = um.Mock(return_value=resp)
            resp.__exit__ = um.Mock(return_value=False)
            return resp

        # urlopen is called twice: once for config, once for addon info
        mock_usbip_env["urlopen"].side_effect = [
            _make_response(config_resp),
            _make_response(SAMPLE_ADDON_INFO_RESPONSE_STARTED),
        ]

        resp = client.get("/api/addon-health")
        data = resp.get_json()
        assert data["ok"] is True
        assert len(data["addons"]) == 1
        assert data["addons"][0]["state"] == "started"
        assert data["addons"][0]["slug"] == "45df7312_zigbee2mqtt"


class TestApiAddonRestart:
    def test_requires_slug(self, client):
        """POST /api/addon-restart without slug returns 400."""
        resp = client.post("/api/addon-restart", json={})
        assert resp.status_code == 400

    def test_restart_success(self, client, mock_usbip_env):
        """POST /api/addon-restart with valid slug."""
        import unittest.mock as um

        resp_mock = um.Mock()
        resp_mock.read.return_value = json.dumps(SAMPLE_ADDON_RESTART_RESPONSE).encode()
        resp_mock.__enter__ = um.Mock(return_value=resp_mock)
        resp_mock.__exit__ = um.Mock(return_value=False)
        mock_usbip_env["urlopen"].return_value = resp_mock

        resp = client.post("/api/addon-restart", json={"slug": "45df7312_zigbee2mqtt"})
        data = resp.get_json()
        assert data["ok"] is True


class TestApiDependentAddonsSave:
    def test_save_selection(self, client, mock_usbip_env):
        """POST /api/dependent-addons saves selection."""
        addons_to_save = [
            {"name": "Zigbee2MQTT", "slug": "45df7312_zigbee2mqtt"},
            {"name": "Z-Wave JS", "slug": "core_zwave_js"},
        ]
        resp = client.post(
            "/api/dependent-addons",
            json={"dependent_addons": addons_to_save},
        )
        data = resp.get_json()
        assert data["ok"] is True

    def test_save_empty_selection(self, client, mock_usbip_env):
        """POST /api/dependent-addons with empty list."""
        resp = client.post(
            "/api/dependent-addons",
            json={"dependent_addons": []},
        )
        data = resp.get_json()
        assert data["ok"] is True
