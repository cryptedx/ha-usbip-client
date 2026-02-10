"""Integration tests for the Flask WebUI API endpoints."""

import json
import os
import sys

import pytest

# Add the webui directory to path so we can import app
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../rootfs/usr/local/bin/webui"))

from testdata import (
    SAMPLE_ADDON_CONFIG,
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
        mock_usbip_env["subprocess"].return_value = pytest.importorskip("unittest.mock").Mock(
            returncode=1, stdout="", stderr="connection refused"
        )
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
        assert "results" in data


class TestApiConfig:
    def test_get(self, client):
        resp = client.get("/api/config")
        data = resp.get_json()
        assert data["ok"] is True
        assert "config" in data

    def test_set(self, client, mock_usbip_env):
        resp = client.post("/api/config", json={"log_level": "debug"})
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
