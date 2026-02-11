"""Unit tests for usbip_lib.config module."""

import json

import pytest

from usbip_lib.config import (
    get_addon_config,
    get_addon_state,
    list_installed_addons,
    restart_addon,
    send_ha_notification,
    set_addon_config,
    supervisor_request,
)

from testdata import (
    SAMPLE_ADDON_CONFIG,
    SAMPLE_ADDON_INFO_RESPONSE_STARTED,
    SAMPLE_ADDON_INFO_RESPONSE_STOPPED,
    SAMPLE_ADDON_RESTART_RESPONSE,
    SAMPLE_ADDONS_LIST_RESPONSE,
    SAMPLE_SUPERVISOR_INFO_RESPONSE,
)


class TestSupervisorRequest:
    def test_get_success(self, mock_supervisor_api):
        result = supervisor_request("GET", "/addons/self/info", token="test-token")
        assert result["result"] == "ok"

    def test_post_with_data(self, mock_supervisor_api):
        result = supervisor_request(
            "POST",
            "/addons/self/options",
            {"options": {"log_level": "debug"}},
            token="test-token",
        )
        assert result["result"] == "ok"

    def test_connection_error(self, mocker):
        mocker.patch(
            "usbip_lib.config.urllib.request.urlopen",
            side_effect=Exception("connection refused"),
        )
        result = supervisor_request("GET", "/addons/self/info", token="test")
        assert result["result"] == "error"
        assert "connection refused" in result["message"]


class TestGetAddonConfig:
    def test_success(self, mock_supervisor_api):
        config = get_addon_config(token="test-token")
        assert config["log_level"] == "info"
        assert config["usbipd_server_address"] == "192.168.1.44"
        assert len(config["devices"]) == 2

    def test_api_error(self, mocker):
        resp = mocker.Mock()
        resp.read.return_value = json.dumps({"result": "error"}).encode()
        resp.__enter__ = mocker.Mock(return_value=resp)
        resp.__exit__ = mocker.Mock(return_value=False)
        mocker.patch("usbip_lib.config.urllib.request.urlopen", return_value=resp)
        config = get_addon_config(token="test")
        assert config == {}


class TestSetAddonConfig:
    def test_success(self, mock_supervisor_api):
        result = set_addon_config({"log_level": "debug"}, token="test-token")
        assert result["result"] == "ok"


class TestSendHaNotification:
    def test_calls_api(self, mock_supervisor_api):
        # Should not raise
        send_ha_notification("Title", "Message", token="test-token")
        assert mock_supervisor_api.called


# ---------------------------------------------------------------------------
# Add-on management tests
# ---------------------------------------------------------------------------


def _make_mock_response(mocker, data):
    """Create a mock HTTP response returning the given data dict."""
    resp = mocker.Mock()
    resp.read.return_value = json.dumps(data).encode()
    resp.__enter__ = mocker.Mock(return_value=resp)
    resp.__exit__ = mocker.Mock(return_value=False)
    return resp


class TestListInstalledAddons:
    def test_success(self, mocker):
        mock_urlopen = mocker.patch("usbip_lib.config.urllib.request.urlopen")
        mock_urlopen.return_value = _make_mock_response(mocker, SAMPLE_ADDONS_LIST_RESPONSE)

        addons = list_installed_addons(token="test-token")
        assert len(addons) == 4
        slugs = [a["slug"] for a in addons]
        assert "45df7312_zigbee2mqtt" in slugs
        assert "core_zwave_js" in slugs
        # Check structure
        z2m = next(a for a in addons if a["slug"] == "45df7312_zigbee2mqtt")
        assert z2m["name"] == "Zigbee2MQTT"
        assert z2m["state"] == "started"

    def test_api_error(self, mocker):
        mock_urlopen = mocker.patch("usbip_lib.config.urllib.request.urlopen")
        mock_urlopen.return_value = _make_mock_response(mocker, {"result": "error"})
        addons = list_installed_addons(token="test")
        assert addons == []

    def test_connection_error(self, mocker):
        mocker.patch(
            "usbip_lib.config.urllib.request.urlopen",
            side_effect=Exception("connection refused"),
        )
        addons = list_installed_addons(token="test")
        assert addons == []


class TestGetAddonState:
    def test_started(self, mocker):
        mock_urlopen = mocker.patch("usbip_lib.config.urllib.request.urlopen")
        mock_urlopen.return_value = _make_mock_response(
            mocker, SAMPLE_ADDON_INFO_RESPONSE_STARTED
        )
        state = get_addon_state("45df7312_zigbee2mqtt", token="test")
        assert state == "started"

    def test_stopped(self, mocker):
        mock_urlopen = mocker.patch("usbip_lib.config.urllib.request.urlopen")
        mock_urlopen.return_value = _make_mock_response(
            mocker, SAMPLE_ADDON_INFO_RESPONSE_STOPPED
        )
        state = get_addon_state("core_zwave_js", token="test")
        assert state == "stopped"

    def test_api_error_returns_unknown(self, mocker):
        mock_urlopen = mocker.patch("usbip_lib.config.urllib.request.urlopen")
        mock_urlopen.return_value = _make_mock_response(mocker, {"result": "error"})
        state = get_addon_state("nonexistent", token="test")
        assert state == "unknown"

    def test_connection_error_returns_unknown(self, mocker):
        mocker.patch(
            "usbip_lib.config.urllib.request.urlopen",
            side_effect=Exception("timeout"),
        )
        state = get_addon_state("something", token="test")
        assert state == "unknown"


class TestRestartAddon:
    def test_success(self, mocker):
        mock_urlopen = mocker.patch("usbip_lib.config.urllib.request.urlopen")
        mock_urlopen.return_value = _make_mock_response(
            mocker, SAMPLE_ADDON_RESTART_RESPONSE
        )
        result = restart_addon("45df7312_zigbee2mqtt", token="test")
        assert result is True

        # Verify correct endpoint was called
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert "/addons/45df7312_zigbee2mqtt/restart" in req.full_url
        assert req.method == "POST"

    def test_failure(self, mocker):
        mock_urlopen = mocker.patch("usbip_lib.config.urllib.request.urlopen")
        mock_urlopen.return_value = _make_mock_response(
            mocker, {"result": "error", "message": "addon not found"}
        )
        result = restart_addon("nonexistent", token="test")
        assert result is False

    def test_connection_error(self, mocker):
        mocker.patch(
            "usbip_lib.config.urllib.request.urlopen",
            side_effect=Exception("connection refused"),
        )
        result = restart_addon("something", token="test")
        assert result is False
