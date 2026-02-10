"""Unit tests for usbip_lib.config module."""

import json

import pytest

from usbip_lib.config import (
    get_addon_config,
    send_ha_notification,
    set_addon_config,
    supervisor_request,
)

from testdata import SAMPLE_ADDON_CONFIG, SAMPLE_SUPERVISOR_INFO_RESPONSE


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
