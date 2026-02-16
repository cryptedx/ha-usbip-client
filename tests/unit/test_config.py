"""Unit tests for usbip_lib.config module."""

import json

import pytest

from usbip_lib.config import (
    get_app_config,
    get_app_state,
    list_installed_apps,
    normalize_notification_config,
    normalize_dependent_apps_config,
    restart_app,
    send_ha_notification,
    set_app_config,
    supervisor_request,
)

from testdata import (
    SAMPLE_APP_CONFIG,
    SAMPLE_APP_INFO_RESPONSE_STARTED,
    SAMPLE_APP_INFO_RESPONSE_STOPPED,
    SAMPLE_APP_RESTART_RESPONSE,
    SAMPLE_APPS_LIST_RESPONSE,
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


class TestGetAppConfig:
    def test_success(self, mock_supervisor_api):
        config = get_app_config(token="test-token")
        assert config["log_level"] == "info"
        assert config["usbipd_server_address"] == "192.168.1.44"
        assert len(config["devices"]) == 2

    def test_api_error(self, mocker):
        resp = mocker.Mock()
        resp.read.return_value = json.dumps({"result": "error"}).encode()
        resp.__enter__ = mocker.Mock(return_value=resp)
        resp.__exit__ = mocker.Mock(return_value=False)
        mocker.patch("usbip_lib.config.urllib.request.urlopen", return_value=resp)
        config = get_app_config(token="test")
        assert config == {}

    def test_migrates_legacy_dependent_key(self, mocker):
        legacy_options = {
            "log_level": "info",
            "dependent_addons": [{"name": "Z2M", "slug": "z2m"}],
        }
        response = {"result": "ok", "data": {"options": legacy_options}}
        resp = mocker.Mock()
        resp.read.return_value = json.dumps(response).encode()
        resp.__enter__ = mocker.Mock(return_value=resp)
        resp.__exit__ = mocker.Mock(return_value=False)
        mocker.patch("usbip_lib.config.urllib.request.urlopen", return_value=resp)

        config = get_app_config(token="test")
        assert config["dependent_apps"] == [{"name": "Z2M", "slug": "z2m"}]
        assert "dependent_addons" not in config


class TestSetAppConfig:
    def test_success(self, mock_supervisor_api):
        result = set_app_config({"log_level": "debug"}, token="test-token")
        assert result["result"] == "ok"

    def test_normalizes_legacy_dependent_key_before_post(self, mocker):
        mock_urlopen = mocker.patch("usbip_lib.config.urllib.request.urlopen")
        resp = mocker.Mock()
        resp.read.return_value = json.dumps({"result": "ok"}).encode()
        resp.__enter__ = mocker.Mock(return_value=resp)
        resp.__exit__ = mocker.Mock(return_value=False)
        mock_urlopen.return_value = resp

        result = set_app_config(
            {"dependent_addons": [{"name": "Z2M", "slug": "z2m"}]},
            token="test-token",
        )
        assert result["result"] == "ok"

        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))
        options = payload["options"]
        assert options["dependent_apps"] == [{"name": "Z2M", "slug": "z2m"}]
        assert "dependent_addons" not in options


class TestNormalizeDependentAppsConfig:
    def test_returns_empty_for_non_dict(self):
        config, changed = normalize_dependent_apps_config([])
        assert config == {}
        assert changed is False

    def test_empty_dict_is_unchanged(self):
        config, changed = normalize_dependent_apps_config({})
        assert config == {}
        assert changed is False

    def test_adds_missing_dependent_apps_key(self):
        config, changed = normalize_dependent_apps_config({"log_level": "info"})
        assert changed is True
        assert config["dependent_apps"] == []


class TestSendHaNotification:
    def test_calls_api(self, mock_supervisor_api):
        # Should not raise
        send_ha_notification("Title", "Message", token="test-token")
        assert mock_supervisor_api.called

    def test_skips_when_notifications_disabled(self, mocker):
        mocker.patch(
            "usbip_lib.config.get_app_config",
            return_value={
                "notifications_enabled": False,
                "notification_types": ["device_lost"],
            },
        )
        mock_supervisor_request = mocker.patch("usbip_lib.config.supervisor_request")

        send_ha_notification(
            "Title",
            "Message",
            notification_type="device_lost",
            token="test-token",
        )

        mock_supervisor_request.assert_not_called()

    def test_filters_by_notification_type(self, mocker):
        mocker.patch(
            "usbip_lib.config.get_app_config",
            return_value={
                "notifications_enabled": True,
                "notification_types": ["app_down"],
            },
        )
        mock_supervisor_request = mocker.patch("usbip_lib.config.supervisor_request")

        send_ha_notification(
            "Title",
            "Message",
            notification_type="device_lost",
            token="test-token",
        )

        mock_supervisor_request.assert_not_called()


class TestNormalizeNotificationConfig:
    def test_returns_empty_for_non_dict(self):
        config, changed = normalize_notification_config([])
        assert config == {}
        assert changed is False

    def test_empty_dict_is_unchanged(self):
        config, changed = normalize_notification_config({})
        assert config == {}
        assert changed is False

    def test_adds_missing_notification_defaults(self):
        config, changed = normalize_notification_config({"log_level": "info"})
        assert changed is True
        assert config["notifications_enabled"] is True
        assert config["notification_types"] == [
            "device_lost",
            "device_recovered",
            "reattach_failed",
            "app_down",
            "app_restarted",
            "app_restart_failed",
            "device_attached",
            "device_detached",
        ]

    def test_deduplicates_and_filters_invalid_types(self):
        config, changed = normalize_notification_config(
            {
                "notifications_enabled": True,
                "notification_types": [
                    "device_lost",
                    "device_lost",
                    "invalid_type",
                    "app_down",
                    123,
                ],
            }
        )
        assert changed is True
        assert config["notification_types"] == ["device_lost", "app_down"]

    def test_replaces_invalid_enabled_value(self):
        config, changed = normalize_notification_config(
            {
                "notifications_enabled": "yes",
                "notification_types": ["device_lost"],
            }
        )
        assert changed is True
        assert config["notifications_enabled"] is True


# ---------------------------------------------------------------------------
# App management tests
# ---------------------------------------------------------------------------


def _make_mock_response(mocker, data):
    """Create a mock HTTP response returning the given data dict."""
    resp = mocker.Mock()
    resp.read.return_value = json.dumps(data).encode()
    resp.__enter__ = mocker.Mock(return_value=resp)
    resp.__exit__ = mocker.Mock(return_value=False)
    return resp


class TestListInstalledApps:
    def test_success(self, mocker):
        mock_urlopen = mocker.patch("usbip_lib.config.urllib.request.urlopen")
        mock_urlopen.return_value = _make_mock_response(
            mocker, SAMPLE_APPS_LIST_RESPONSE
        )

        apps = list_installed_apps(token="test-token")
        assert len(apps) == 4
        slugs = [a["slug"] for a in apps]
        assert "45df7312_zigbee2mqtt" in slugs
        assert "core_zwave_js" in slugs
        # Check structure
        z2m = next(a for a in apps if a["slug"] == "45df7312_zigbee2mqtt")
        assert z2m["name"] == "Zigbee2MQTT"
        assert z2m["state"] == "started"

    def test_api_error(self, mocker):
        mock_urlopen = mocker.patch("usbip_lib.config.urllib.request.urlopen")
        mock_urlopen.return_value = _make_mock_response(mocker, {"result": "error"})
        apps = list_installed_apps(token="test")
        assert apps == []

    def test_connection_error(self, mocker):
        mocker.patch(
            "usbip_lib.config.urllib.request.urlopen",
            side_effect=Exception("connection refused"),
        )
        apps = list_installed_apps(token="test")
        assert apps == []


class TestGetAppState:
    def test_started(self, mocker):
        mock_urlopen = mocker.patch("usbip_lib.config.urllib.request.urlopen")
        mock_urlopen.return_value = _make_mock_response(
            mocker, SAMPLE_APP_INFO_RESPONSE_STARTED
        )
        state = get_app_state("45df7312_zigbee2mqtt", token="test")
        assert state == "started"

    def test_stopped(self, mocker):
        mock_urlopen = mocker.patch("usbip_lib.config.urllib.request.urlopen")
        mock_urlopen.return_value = _make_mock_response(
            mocker, SAMPLE_APP_INFO_RESPONSE_STOPPED
        )
        state = get_app_state("core_zwave_js", token="test")
        assert state == "stopped"

    def test_api_error_returns_unknown(self, mocker):
        mock_urlopen = mocker.patch("usbip_lib.config.urllib.request.urlopen")
        mock_urlopen.return_value = _make_mock_response(mocker, {"result": "error"})
        state = get_app_state("nonexistent", token="test")
        assert state == "unknown"

    def test_connection_error_returns_unknown(self, mocker):
        mocker.patch(
            "usbip_lib.config.urllib.request.urlopen",
            side_effect=Exception("timeout"),
        )
        state = get_app_state("something", token="test")
        assert state == "unknown"


class TestRestartApp:
    def test_success(self, mocker):
        mock_urlopen = mocker.patch("usbip_lib.config.urllib.request.urlopen")
        mock_urlopen.return_value = _make_mock_response(
            mocker, SAMPLE_APP_RESTART_RESPONSE
        )
        result = restart_app("45df7312_zigbee2mqtt", token="test")
        assert result is True

        # Verify correct endpoint was called
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert "/addons/45df7312_zigbee2mqtt/restart" in req.full_url
        assert req.method == "POST"

    def test_failure(self, mocker):
        mock_urlopen = mocker.patch("usbip_lib.config.urllib.request.urlopen")
        mock_urlopen.return_value = _make_mock_response(
            mocker, {"result": "error", "message": "app not found"}
        )
        result = restart_app("nonexistent", token="test")
        assert result is False

    def test_connection_error(self, mocker):
        mocker.patch(
            "usbip_lib.config.urllib.request.urlopen",
            side_effect=Exception("connection refused"),
        )
        result = restart_app("something", token="test")
        assert result is False
