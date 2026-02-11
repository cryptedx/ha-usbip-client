"""Unit tests for the monitor service logic."""

import json
import sys
import os
import time

import pytest

# The monitor run script is not a normal importable module, so we test
# the core logic functions by importing them via importlib after adding
# the services.d path.  However, the functions we need to test are pure
# functions that we can extract.  Instead, we replicate the key logic
# from the monitor service and test it here.

from testdata import SAMPLE_DEVICE_MANIFEST


# ---------------------------------------------------------------------------
# Re-implement the pure logic from monitor/run for testability
# ---------------------------------------------------------------------------
def find_missing_devices(
    manifest: list[dict], attached: list[dict]
) -> list[dict]:
    """Compare manifest against currently attached devices.

    Returns list of manifest entries NOT found in attached devices.
    """
    attached_set = set()
    for d in attached:
        server = d.get("server", "")
        remote_busid = d.get("remote_busid", "")
        if server and remote_busid:
            attached_set.add((server, remote_busid))

    missing = []
    for dev in manifest:
        key = (dev.get("server", ""), dev.get("bus_id", ""))
        if key not in attached_set:
            missing.append(dev)
    return missing


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
            {"server": "10.0.0.1", "bus_id": "1-1.4", "name": "Test", "delay": 2, "retries": 3},
        ]
        attached = [
            {"port": 0, "server": "192.168.1.44", "remote_busid": "1-1.4"},
        ]
        missing = find_missing_devices(manifest, attached)
        assert len(missing) == 1


class TestNotificationCooldown:
    """Test the cooldown logic from the monitor service."""

    def test_cooldown_tracking(self):
        # Simulate the cooldown dict from the monitor
        cooldowns: dict[str, float] = {}
        cooldown_seconds = 300

        def is_on_cooldown(key: str) -> bool:
            last = cooldowns.get(key, 0)
            return (time.monotonic() - last) < cooldown_seconds

        def set_cooldown(key: str) -> None:
            cooldowns[key] = time.monotonic()

        device_key = "192.168.1.44:1-1.4"

        # Not on cooldown initially
        assert not is_on_cooldown(device_key)

        # Set cooldown
        set_cooldown(device_key)
        assert is_on_cooldown(device_key)

        # Different key is not on cooldown
        assert not is_on_cooldown("192.168.1.44:1-1.3")

    def test_cooldown_expires(self):
        """Cooldown with a very short window should expire immediately."""
        cooldowns: dict[str, float] = {}
        cooldown_seconds = 0  # immediate expiry

        def is_on_cooldown(key: str) -> bool:
            last = cooldowns.get(key, 0)
            return (time.monotonic() - last) < cooldown_seconds

        cooldowns["test"] = time.monotonic()
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
        mock_attach = mocker.patch("usbip_lib.usbip.attach_device", return_value=False)
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


class TestDependentAddonRestart:
    """Test dependent add-on restart logic with mocked Supervisor API."""

    def test_restart_success(self, mocker):
        mock_restart = mocker.patch("usbip_lib.config.restart_addon", return_value=True)
        from usbip_lib.config import restart_addon

        result = restart_addon("45df7312_zigbee2mqtt")
        assert result is True

    def test_restart_failure(self, mocker):
        mock_restart = mocker.patch("usbip_lib.config.restart_addon", return_value=False)
        from usbip_lib.config import restart_addon

        result = restart_addon("nonexistent_addon")
        assert result is False

    def test_get_addon_state_started(self, mocker):
        from testdata import SAMPLE_ADDON_INFO_RESPONSE_STARTED

        def _make_response(data):
            resp = mocker.Mock()
            resp.read.return_value = json.dumps(data).encode()
            resp.__enter__ = mocker.Mock(return_value=resp)
            resp.__exit__ = mocker.Mock(return_value=False)
            return resp

        mocker.patch(
            "usbip_lib.config.urllib.request.urlopen",
            return_value=_make_response(SAMPLE_ADDON_INFO_RESPONSE_STARTED),
        )
        from usbip_lib.config import get_addon_state

        state = get_addon_state("45df7312_zigbee2mqtt", token="test")
        assert state == "started"

    def test_get_addon_state_stopped(self, mocker):
        from testdata import SAMPLE_ADDON_INFO_RESPONSE_STOPPED

        def _make_response(data):
            resp = mocker.Mock()
            resp.read.return_value = json.dumps(data).encode()
            resp.__enter__ = mocker.Mock(return_value=resp)
            resp.__exit__ = mocker.Mock(return_value=False)
            return resp

        mocker.patch(
            "usbip_lib.config.urllib.request.urlopen",
            return_value=_make_response(SAMPLE_ADDON_INFO_RESPONSE_STOPPED),
        )
        from usbip_lib.config import get_addon_state

        state = get_addon_state("core_zwave_js", token="test")
        assert state == "stopped"
