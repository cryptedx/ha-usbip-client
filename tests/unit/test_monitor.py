"""Unit tests for the monitor service logic."""

import json

import pytest

from usbip_lib.monitor import (
    attempt_reattach,
    check_dependent_app_health,
    clear_app_health_state,
    clear_flapping_state,
    clear_cooldowns,
    evaluate_flapping_clear,
    find_missing_devices,
    is_on_cooldown,
    record_flapping_recovery,
    run_post_reattach_actions,
    restart_dependent_apps,
    select_apps_to_restart,
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

    def test_zero_reattach_retries_disables_attempt(self, mocker):
        logger = mocker.Mock()
        attach = mocker.patch("usbip_lib.monitor.attach_device")
        events = mocker.patch("usbip_lib.monitor.write_event")

        result = attempt_reattach(
            {"name": "Stick", "server": "usbip-host", "bus_id": "1-2"},
            retries=0,
            logger=logger,
        )

        assert result is None
        attach.assert_not_called()
        events.assert_not_called()


class TestFlappingDetection:
    def setup_method(self):
        clear_flapping_state()

    def test_escalates_to_warning_and_critical(self):
        device_key = "192.168.1.44:1-1.4"

        assert record_flapping_recovery(device_key, now=1000.0) is None
        assert record_flapping_recovery(device_key, now=1010.0) is None

        warning = record_flapping_recovery(device_key, now=1020.0)
        assert warning is not None
        assert warning["level"] == "warning"
        assert warning["count"] == 3

        assert record_flapping_recovery(device_key, now=1030.0) is None

        critical = record_flapping_recovery(device_key, now=1040.0)
        assert critical is not None
        assert critical["level"] == "critical"
        assert critical["count"] == 5

    def test_window_pruning_prevents_false_escalation(self):
        device_key = "192.168.1.44:1-1.4"

        assert record_flapping_recovery(device_key, now=1000.0) is None
        assert record_flapping_recovery(device_key, now=1010.0) is None
        # older recoveries fall outside 600s window
        assert record_flapping_recovery(device_key, now=1701.0) is None

    def test_clears_after_stable_window(self):
        device_key = "192.168.1.44:1-1.4"
        record_flapping_recovery(device_key, now=1000.0)
        record_flapping_recovery(device_key, now=1010.0)
        warning = record_flapping_recovery(device_key, now=1020.0)
        assert warning and warning["level"] == "warning"

        assert evaluate_flapping_clear(device_key, now=1800.0) is None

        cleared = evaluate_flapping_clear(device_key, now=1925.0)
        assert cleared is not None
        assert cleared["level"] == "none"
        assert cleared["previous_level"] == "warning"


class TestDependentAppRestart:
    """Test dependent app restart logic with mocked Supervisor API."""

    def setup_method(self):
        clear_app_health_state()

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

    def test_restart_dependent_apps_retries_then_succeeds(self, mocker):
        logger = mocker.Mock()
        mocker.patch("usbip_lib.monitor.time.sleep")
        restart_mock = mocker.patch(
            "usbip_lib.monitor.restart_app", side_effect=[False, True]
        )
        write_event_mock = mocker.patch("usbip_lib.monitor.write_event")
        notify_mock = mocker.patch("usbip_lib.monitor.send_ha_notification")

        restart_dependent_apps(
            [{"name": "Z2M", "slug": "45df7312_zigbee2mqtt"}],
            restart_retries=2,
            logger=logger,
        )

        assert restart_mock.call_count == 2
        write_event_mock.assert_called_with(
            "app_restart_ok", "Restarted Z2M", device="Z2M"
        )
        notify_mock.assert_called_with(
            "USB/IP: App Restarted",
            "Z2M was restarted after USB device recovery.",
            notification_type="app_restarted",
        )

    def test_zero_restart_retries_disables_restart(self, mocker):
        logger = mocker.Mock()
        restart = mocker.patch("usbip_lib.monitor.restart_app")
        notify = mocker.patch("usbip_lib.monitor.send_ha_notification")
        events = mocker.patch("usbip_lib.monitor.write_event")

        restart_dependent_apps([{"name": "Z2M", "slug": "z2m"}], 0, logger)

        restart.assert_not_called()
        notify.assert_not_called()
        events.assert_not_called()

    def test_zero_restart_retries_does_not_claim_health_restart(self, mocker):
        logger = mocker.Mock()
        mocker.patch("usbip_lib.monitor.get_app_state", return_value="stopped")
        restart = mocker.patch("usbip_lib.monitor.restart_app")
        mocker.patch("usbip_lib.monitor.send_ha_notification")
        mocker.patch("usbip_lib.monitor.write_event")

        check_dependent_app_health(
            [{"name": "Z2M", "slug": "z2m"}],
            restart_retries=0,
            logger=logger,
        )

        restart.assert_not_called()
        assert not any(
            call.args and "Attempting to restart unhealthy app" in call.args[0]
            for call in logger.info.call_args_list
        )

    def test_check_dependent_app_health_retries_error_state(self, mocker):
        logger = mocker.Mock()
        mocker.patch("usbip_lib.monitor.time.sleep")
        mocker.patch("usbip_lib.monitor.get_app_state", return_value="error")
        restart_mock = mocker.patch("usbip_lib.monitor.restart_app", return_value=True)
        write_event_mock = mocker.patch("usbip_lib.monitor.write_event")

        check_dependent_app_health(
            [{"name": "Z2M", "slug": "45df7312_zigbee2mqtt"}],
            restart_retries=2,
            logger=logger,
        )

        restart_mock.assert_called_once_with("45df7312_zigbee2mqtt")
        assert any(
            call.args[:2] == ("app_health_fail", "Z2M is error")
            for call in write_event_mock.call_args_list
        )

    def test_check_dependent_app_health_restarts_stopped_state(self, mocker):
        logger = mocker.Mock()
        mocker.patch("usbip_lib.monitor.time.sleep")
        mocker.patch("usbip_lib.monitor.get_app_state", return_value="stopped")
        restart_mock = mocker.patch("usbip_lib.monitor.restart_app", return_value=True)
        notify_mock = mocker.patch("usbip_lib.monitor.send_ha_notification")
        write_event_mock = mocker.patch("usbip_lib.monitor.write_event")

        check_dependent_app_health(
            [{"name": "Z2M", "slug": "45df7312_zigbee2mqtt"}],
            restart_retries=2,
            logger=logger,
        )

        restart_mock.assert_called_once_with("45df7312_zigbee2mqtt")
        assert any(
            call.args[:2] == ("app_health_fail", "Z2M is stopped")
            for call in write_event_mock.call_args_list
        )
        assert any(
            call.args[0] == "USB/IP: App Restarted"
            and "due to stopped state." in call.args[1]
            for call in notify_mock.call_args_list
        )

    def test_check_dependent_app_health_does_not_restart_unknown_state(self, mocker):
        logger = mocker.Mock()
        mocker.patch("usbip_lib.monitor.time.sleep")
        mocker.patch("usbip_lib.monitor.get_app_state", return_value="unknown")
        restart_mock = mocker.patch("usbip_lib.monitor.restart_app", return_value=True)
        mocker.patch("usbip_lib.monitor.send_ha_notification")
        mocker.patch("usbip_lib.monitor.write_event")

        check_dependent_app_health(
            [{"name": "Z2M", "slug": "45df7312_zigbee2mqtt"}],
            restart_retries=2,
            logger=logger,
        )

        restart_mock.assert_not_called()

    def test_check_dependent_app_health_retries_on_next_cycle_when_still_unhealthy(
        self, mocker
    ):
        logger = mocker.Mock()
        mocker.patch("usbip_lib.monitor.time.sleep")
        mocker.patch("usbip_lib.monitor.get_app_state", return_value="stopped")
        restart_mock = mocker.patch("usbip_lib.monitor.restart_app", return_value=True)
        mocker.patch("usbip_lib.monitor.send_ha_notification")
        mocker.patch("usbip_lib.monitor.write_event")

        apps = [{"name": "Z2M", "slug": "45df7312_zigbee2mqtt"}]
        check_dependent_app_health(apps, restart_retries=1, logger=logger)
        check_dependent_app_health(apps, restart_retries=1, logger=logger)

        assert restart_mock.call_count == 2

    def test_check_dependent_app_health_does_not_spam_notifications_across_cycles(
        self, mocker
    ):
        logger = mocker.Mock()
        mocker.patch("usbip_lib.monitor.time.sleep")
        mocker.patch("usbip_lib.monitor.get_app_state", return_value="stopped")
        mocker.patch("usbip_lib.monitor.restart_app", return_value=True)
        notify_mock = mocker.patch("usbip_lib.monitor.send_ha_notification")
        write_event_mock = mocker.patch("usbip_lib.monitor.write_event")

        apps = [{"name": "Z2M", "slug": "45df7312_zigbee2mqtt"}]
        check_dependent_app_health(apps, restart_retries=1, logger=logger)
        check_dependent_app_health(apps, restart_retries=1, logger=logger)

        app_down_calls = [
            c
            for c in notify_mock.call_args_list
            if c.kwargs.get("notification_type") == "app_down"
        ]
        assert len(app_down_calls) == 1

        health_fail_events = [
            c
            for c in write_event_mock.call_args_list
            if c.args[:1] == ("app_health_fail",)
        ]
        assert len(health_fail_events) == 1

    @pytest.mark.parametrize(
        ("outcome", "notification_type", "event_type"),
        [
            (False, "app_restart_failed", "app_restart_fail"),
            (True, "app_restarted", "app_restart_ok"),
        ],
    )
    def test_repeated_restart_result_is_reported_once_across_cycles(
        self, mocker, outcome, notification_type, event_type
    ):
        logger = mocker.Mock()
        mocker.patch("usbip_lib.monitor.time.sleep")
        mocker.patch("usbip_lib.monitor.get_app_state", return_value="stopped")
        restart = mocker.patch("usbip_lib.monitor.restart_app", return_value=outcome)
        notify = mocker.patch("usbip_lib.monitor.send_ha_notification")
        events = mocker.patch("usbip_lib.monitor.write_event")

        apps = [{"name": "Z2M", "slug": "z2m"}]
        check_dependent_app_health(apps, restart_retries=1, logger=logger)
        check_dependent_app_health(apps, restart_retries=1, logger=logger)

        assert restart.call_count == 2
        assert (
            sum(
                call.kwargs.get("notification_type") == notification_type
                for call in notify.call_args_list
            )
            == 1
        )
        assert (
            sum(call.args[:1] == (event_type,) for call in events.call_args_list) == 1
        )

    @pytest.mark.parametrize(
        ("outcomes", "expected_notifications", "expected_events"),
        [
            (
                [False, True],
                ["app_restart_failed", "app_restarted"],
                ["app_restart_fail", "app_restart_ok"],
            ),
            (
                [True, False],
                ["app_restarted", "app_restart_failed"],
                ["app_restart_ok", "app_restart_fail"],
            ),
        ],
    )
    def test_changed_restart_result_is_reported_across_cycles(
        self, mocker, outcomes, expected_notifications, expected_events
    ):
        logger = mocker.Mock()
        mocker.patch("usbip_lib.monitor.time.sleep")
        mocker.patch("usbip_lib.monitor.get_app_state", return_value="stopped")
        restart = mocker.patch("usbip_lib.monitor.restart_app", side_effect=outcomes)
        notify = mocker.patch("usbip_lib.monitor.send_ha_notification")
        events = mocker.patch("usbip_lib.monitor.write_event")

        apps = [{"name": "Z2M", "slug": "z2m"}]
        check_dependent_app_health(apps, restart_retries=1, logger=logger)
        check_dependent_app_health(apps, restart_retries=1, logger=logger)

        assert restart.call_count == 2
        assert [
            call.kwargs.get("notification_type")
            for call in notify.call_args_list
            if call.kwargs.get("notification_type")
            in {"app_restarted", "app_restart_failed"}
        ] == expected_notifications
        assert [
            call.args[0]
            for call in events.call_args_list
            if call.args[:1] in {("app_restart_ok",), ("app_restart_fail",)}
        ] == expected_events

    def test_restart_results_are_tracked_independently_per_app(self, mocker):
        logger = mocker.Mock()
        mocker.patch("usbip_lib.monitor.time.sleep")
        mocker.patch("usbip_lib.monitor.get_app_state", return_value="stopped")
        restart = mocker.patch(
            "usbip_lib.monitor.restart_app",
            side_effect=[False, True, True, False],
        )
        mocker.patch("usbip_lib.monitor.send_ha_notification")
        events = mocker.patch("usbip_lib.monitor.write_event")

        apps = [
            {"name": "App A", "slug": "app_a"},
            {"name": "App B", "slug": "app_b"},
        ]
        check_dependent_app_health(apps, restart_retries=1, logger=logger)
        check_dependent_app_health(apps, restart_retries=1, logger=logger)

        assert restart.call_count == 4
        assert [
            call.args[0]
            for call in events.call_args_list
            if call.kwargs.get("device") == "App A"
            and call.args[:1] in {("app_restart_ok",), ("app_restart_fail",)}
        ] == ["app_restart_fail", "app_restart_ok"]
        assert [
            call.args[0]
            for call in events.call_args_list
            if call.kwargs.get("device") == "App B"
            and call.args[:1] in {("app_restart_ok",), ("app_restart_fail",)}
        ] == ["app_restart_ok", "app_restart_fail"]

    def test_health_recovery_resets_restart_result_reporting(self, mocker):
        logger = mocker.Mock()
        mocker.patch("usbip_lib.monitor.time.sleep")
        mocker.patch(
            "usbip_lib.monitor.get_app_state",
            side_effect=["stopped", "started", "stopped"],
        )
        restart = mocker.patch("usbip_lib.monitor.restart_app", return_value=False)
        notify = mocker.patch("usbip_lib.monitor.send_ha_notification")
        events = mocker.patch("usbip_lib.monitor.write_event")

        apps = [{"name": "Z2M", "slug": "z2m"}]
        for _ in range(3):
            check_dependent_app_health(apps, restart_retries=1, logger=logger)

        assert restart.call_count == 2
        assert (
            sum(
                call.kwargs.get("notification_type") == "app_restart_failed"
                for call in notify.call_args_list
            )
            == 2
        )
        assert any(
            call.args[:1] == ("app_health_ok",) for call in events.call_args_list
        )

    def test_disabled_result_does_not_hide_first_later_restart_result(self, mocker):
        logger = mocker.Mock()
        mocker.patch("usbip_lib.monitor.time.sleep")
        mocker.patch("usbip_lib.monitor.get_app_state", return_value="stopped")
        restart = mocker.patch("usbip_lib.monitor.restart_app", return_value=False)
        notify = mocker.patch("usbip_lib.monitor.send_ha_notification")
        events = mocker.patch("usbip_lib.monitor.write_event")

        apps = [{"name": "Z2M", "slug": "z2m"}]
        check_dependent_app_health(apps, restart_retries=0, logger=logger)
        check_dependent_app_health(apps, restart_retries=1, logger=logger)

        restart.assert_called_once_with("z2m")
        assert (
            sum(
                call.kwargs.get("notification_type") == "app_restart_failed"
                for call in notify.call_args_list
            )
            == 1
        )
        assert (
            sum(
                call.args[:1] == ("app_restart_fail",) for call in events.call_args_list
            )
            == 1
        )


class TestSelectAppsToRestart:
    """Which dependent apps restart after devices were reattached."""

    ZWAVE = {"name": "Z-Wave Stick", "server": "pi", "bus_id": "1-1.2"}
    ZIGBEE = {"name": "Zigbee Stick", "server": "pi", "bus_id": "1-1.3"}
    MANIFEST = [ZWAVE, ZIGBEE]
    ZWAVE_APP = {"name": "Z-Wave JS", "slug": "zwave", "devices": ["Z-Wave Stick"]}
    ZIGBEE_APP = {"name": "Z2M", "slug": "z2m", "devices": ["Zigbee Stick"]}

    def _select(self, mocker, apps, reattached):
        logger = mocker.Mock()
        return select_apps_to_restart(apps, reattached, self.MANIFEST, logger), logger

    def test_app_without_devices_restarts_after_any_recovery(self, mocker):
        apps = [{"name": "Z2M", "slug": "z2m"}, {"name": "Z-Wave", "slug": "zwave"}]

        selected, logger = self._select(mocker, apps, [self.ZWAVE])

        assert selected == apps
        logger.warning.assert_not_called()

    def test_empty_device_list_counts_as_no_mapping(self, mocker):
        app = {"name": "Z2M", "slug": "z2m", "devices": []}

        selected, logger = self._select(mocker, [app], [self.ZWAVE])

        assert selected == [app]
        logger.warning.assert_not_called()

    def test_mapped_app_restarts_only_for_its_own_device(self, mocker):
        apps = [self.ZIGBEE_APP, self.ZWAVE_APP]

        selected, logger = self._select(mocker, apps, [self.ZWAVE])

        assert selected == [self.ZWAVE_APP]
        logger.warning.assert_not_called()

    def test_skipped_app_is_named_in_the_log(self, mocker):
        _, logger = self._select(
            mocker, [self.ZIGBEE_APP, self.ZWAVE_APP], [self.ZWAVE]
        )

        logged = [call.args[1:] for call in logger.info.call_args_list]
        assert ("Z2M", "z2m") in logged
        assert ("Z-Wave JS", "zwave") not in logged

    def test_app_with_two_devices_restarts_for_either(self, mocker):
        app = {
            "name": "Both",
            "slug": "both",
            "devices": ["Z-Wave Stick", "Zigbee Stick"],
        }

        for device in (self.ZWAVE, self.ZIGBEE):
            selected, _ = self._select(mocker, [app], [device])
            assert selected == [app]

    def test_unmapped_app_restarts_next_to_mapped_ones(self, mocker):
        unmapped = {"name": "Other", "slug": "other"}

        selected, _ = self._select(
            mocker, [self.ZIGBEE_APP, unmapped, self.ZWAVE_APP], [self.ZWAVE]
        )

        assert selected == [unmapped, self.ZWAVE_APP]

    def test_unknown_device_name_restarts_app_and_warns(self, mocker):
        typo = {"name": "Z2M", "slug": "z2m", "devices": ["Zigbe Stick"]}

        selected, logger = self._select(mocker, [typo], [self.ZIGBEE])

        assert selected == [typo]
        logger.warning.assert_called_once()
        assert ["Zigbe Stick"] in logger.warning.call_args.args

    def test_one_unknown_name_disables_the_mapping_of_that_app(self, mocker):
        app = {
            "name": "Z2M",
            "slug": "z2m",
            "devices": ["Zigbee Stick", "Renamed Stick"],
        }

        selected, logger = self._select(mocker, [app], [self.ZWAVE])

        assert selected == [app]
        logger.warning.assert_called_once()

    def test_malformed_device_list_counts_as_no_mapping(self, mocker):
        app = {"name": "Z2M", "slug": "z2m", "devices": 5}

        selected, _ = self._select(mocker, [app], [self.ZWAVE])

        assert selected == [app]

    def test_nothing_reattached_selects_nothing(self, mocker):
        apps = [{"name": "Z2M", "slug": "z2m"}, self.ZWAVE_APP]

        selected, logger = self._select(mocker, apps, [])

        assert selected == []
        logger.warning.assert_not_called()


class TestManifestRefresh:
    def test_refresh_device_manifest_rediscovers_configured_devices(self, mocker):
        from usbip_lib.monitor import refresh_device_manifest

        logger = mocker.Mock()
        config = {
            "usbipd_server_address": "192.168.1.44",
            "devices": [{"name": "Zigbee", "device_or_bus_id": "10c4:ea60"}],
        }
        discovery = [
            {
                "server": "192.168.1.44",
                "busid": "1-1.2",
                "name": "Silicon Labs CP210x UART Bridge",
                "device_id": "10c4:ea60",
            }
        ]
        manifest = [
            {
                "server": "192.168.1.44",
                "bus_id": "1-1.2",
                "name": "Zigbee",
                "delay": 2,
                "retries": 3,
            }
        ]
        mocker.patch(
            "usbip_lib.monitor.get_unique_servers", return_value={"192.168.1.44"}
        )
        discover_mock = mocker.patch(
            "usbip_lib.monitor.discover_devices", return_value=discovery
        )
        build_mock = mocker.patch(
            "usbip_lib.monitor.build_device_manifest", return_value=manifest
        )
        write_mock = mocker.patch("usbip_lib.monitor.write_device_manifest")

        assert refresh_device_manifest(config, logger) == manifest
        discover_mock.assert_called_once_with(["192.168.1.44"])
        build_mock.assert_called_once_with(config, discovery)
        write_mock.assert_called_once_with(manifest)


class TestPostReattachActions:
    def test_runs_post_action_with_capped_timeout(self, mocker):
        logger = mocker.Mock()
        response = mocker.Mock()
        response.status = 200
        response.__enter__ = mocker.Mock(return_value=response)
        response.__exit__ = mocker.Mock(return_value=False)
        urlopen_mock = mocker.patch(
            "usbip_lib.monitor.urllib.request.urlopen",
            return_value=response,
        )
        write_event_mock = mocker.patch("usbip_lib.monitor.write_event")

        run_post_reattach_actions(
            [
                {
                    "name": "Companion surface rescan",
                    "url": "http://companion:8000/api/surfaces/rescan",
                    "method": "POST",
                    "timeout": 30,
                }
            ],
            logger=logger,
        )

        req = urlopen_mock.call_args.args[0]
        assert req.full_url == "http://companion:8000/api/surfaces/rescan"
        assert req.get_method() == "POST"
        assert urlopen_mock.call_args.kwargs["timeout"] == 3
        write_event_mock.assert_called_with(
            "post_reattach_ok",
            "Companion surface rescan returned HTTP 200",
            device="Companion surface rescan",
        )

    def test_skips_invalid_post_action_url(self, mocker):
        logger = mocker.Mock()
        urlopen_mock = mocker.patch("usbip_lib.monitor.urllib.request.urlopen")
        write_event_mock = mocker.patch("usbip_lib.monitor.write_event")

        run_post_reattach_actions(
            [{"name": "Bad action", "url": "file:///tmp/nope", "method": "POST"}],
            logger=logger,
        )

        urlopen_mock.assert_not_called()
        write_event_mock.assert_called_with(
            "post_reattach_fail",
            "Bad action has an invalid URL",
            device="Bad action",
        )
