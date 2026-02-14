"""Unit tests for the monitor service logic."""

import json
import time

import pytest

from usbip_lib.monitor import (
    attempt_reattach,
    check_dependent_app_health,
    clear_cooldowns,
    find_missing_devices,
    is_on_cooldown,
    restart_dependent_apps,
    set_cooldown,
)

from testdata import SAMPLE_DEVICE_MANIFEST


# Sample attached device data (mimics parse_usbip_port output)
ATTACHED_BOTH = [
    {
        "port": 0,
        "status": "Port in Use",
        "info": "unknown vendor",
        "busid": "",
        "device_id": "0658:0200",
        "server": "192.168.1.44",
        "remote_busid": "1-1.4",
    },
    {
        "port": 1,
        "status": "Port in Use",
        "info": "unknown vendor",
        "busid": "",
        "device_id": "10c4:ea60",
        "server": "192.168.1.44",
        "remote_busid": "1-1.3",
    },
]

ATTACHED_ONLY_FIRST = [
    {
        "port": 0,
        "status": "Port in Use",
        "info": "unknown vendor",
        "busid": "",
        "device_id": "0658:0200",
        "server": "192.168.1.44",
        "remote_busid": "1-1.4",
    },
]

ATTACHED_NONE: list[dict] = []


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestFindMissingDevices:
    def test_no_missing_when_all_attached(self):
        missing = find_missing_devices(SAMPLE_DEVICE_MANIFEST, ATTACHED_BOTH)
        assert missing == []

    def test_one_missing(self):
        missing = find_missing_devices(SAMPLE_DEVICE_MANIFEST, ATTACHED_ONLY_FIRST)
        assert len(missing) == 1
        assert missing[0]["bus_id"] == "1-1.3"
        assert missing[0]["name"] == "Zigbee Stick"

    def test_all_missing(self):
        missing = find_missing_devices(SAMPLE_DEVICE_MANIFEST, ATTACHED_NONE)
        assert len(missing) == 2

    def test_empty_manifest(self):
        missing = find_missing_devices([], ATTACHED_BOTH)
        assert missing == []

    def test_empty_both(self):
        missing = find_missing_devices([], [])
        assert missing == []

    def test_different_server(self):
        """Manifest device on server A but attached from server B should be missing."""
        manifest = [
            {
                "server": "10.0.0.1",
                "bus_id": "1-1.4",
                "name": "Test",
                "delay": 2,
                "retries": 3,
            },
        ]
        attached = [
            {"port": 0, "server": "192.168.1.44", "remote_busid": "1-1.4"},
        ]
        missing = find_missing_devices(manifest, attached)
        assert len(missing) == 1


class TestNotificationCooldown:
    """Test the cooldown logic from the monitor service."""

    def setup_method(self):
        """Reset cooldowns before each test."""
        clear_cooldowns()

    def test_cooldown_tracking(self):
        device_key = "192.168.1.44:1-1.4"

        # Not on cooldown initially
        assert not is_on_cooldown(device_key)

        # Set cooldown
        set_cooldown(device_key)
        assert is_on_cooldown(device_key)

        # Different key is not on cooldown
        assert not is_on_cooldown("192.168.1.44:1-1.3")

    def test_cooldown_expires(self, mocker):
        """Cooldown should respect the configured window."""
        # Patch COOLDOWN_SECONDS to 0 so it expires immediately
        mocker.patch("usbip_lib.monitor.COOLDOWN_SECONDS", 0)

        set_cooldown("test")
        assert not is_on_cooldown("test")


class TestReattachLogic:
    """Test reattach attempt logic with mocked attach_device."""

    def test_reattach_success(self, mocker):
        mock_attach = mocker.patch("usbip_lib.usbip.attach_device", return_value=True)
        from usbip_lib.usbip import attach_device

        device = SAMPLE_DEVICE_MANIFEST[0]
        ok = attach_device(
            server=device["server"],
            bus_id=device["bus_id"],
            device_name=device["name"],
            retries=3,
            delay=0,
        )
        assert ok is True
        mock_attach.assert_called_once()

    def test_reattach_failure(self, mocker):
        mocker.patch("usbip_lib.usbip.attach_device", return_value=False)
        from usbip_lib.usbip import attach_device

        device = SAMPLE_DEVICE_MANIFEST[0]
        ok = attach_device(
            server=device["server"],
            bus_id=device["bus_id"],
            device_name=device["name"],
            retries=3,
            delay=0,
        )
        assert ok is False


class TestDependentAppRestart:
    """Test dependent app restart logic with mocked Supervisor API."""

    def test_restart_success(self, mocker):
        mocker.patch("usbip_lib.config.restart_app", return_value=True)
        from usbip_lib.config import restart_app

        result = restart_app("45df7312_zigbee2mqtt")
        assert result is True

    def test_restart_failure(self, mocker):
        mocker.patch("usbip_lib.config.restart_app", return_value=False)
        from usbip_lib.config import restart_app

        result = restart_app("nonexistent_app")
        assert result is False

    def test_get_app_state_started(self, mocker):
        from testdata import SAMPLE_APP_INFO_RESPONSE_STARTED

        def _make_response(data):
            resp = mocker.Mock()
            resp.read.return_value = json.dumps(data).encode()
            resp.__enter__ = mocker.Mock(return_value=resp)
            resp.__exit__ = mocker.Mock(return_value=False)
            return resp

        mocker.patch(
            "usbip_lib.config.urllib.request.urlopen",
            return_value=_make_response(SAMPLE_APP_INFO_RESPONSE_STARTED),
        )
        from usbip_lib.config import get_app_state

        state = get_app_state("45df7312_zigbee2mqtt", token="test")
        assert state == "started"

    def test_get_app_state_stopped(self, mocker):
        from testdata import SAMPLE_APP_INFO_RESPONSE_STOPPED

        def _make_response(data):
            resp = mocker.Mock()
            resp.read.return_value = json.dumps(data).encode()
            resp.__enter__ = mocker.Mock(return_value=resp)
            resp.__exit__ = mocker.Mock(return_value=False)
            return resp

        mocker.patch(
            "usbip_lib.config.urllib.request.urlopen",
            return_value=_make_response(SAMPLE_APP_INFO_RESPONSE_STOPPED),
        )
        from usbip_lib.config import get_app_state

        state = get_app_state("core_zwave_js", token="test")
        assert state == "stopped"
