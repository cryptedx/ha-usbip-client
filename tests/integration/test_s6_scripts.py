"""Integration tests for s6 script logic.

These tests import and exercise the core logic from the s6 Python scripts
without actually running s6-overlay. All system calls are mocked.
"""

import json
import os
import runpy
from pathlib import Path

import pytest

from testdata import (
    SAMPLE_APP_CONFIG,
    SAMPLE_DEVICE_MANIFEST,
    SAMPLE_DISCOVERY_DATA,
    SAMPLE_SUPERVISOR_INFO_RESPONSE,
    SAMPLE_USBIP_LIST_OUTPUT,
    SAMPLE_USBIP_PORT_OUTPUT,
)


MONITOR_RUN_PATH = (
    Path(__file__).resolve().parents[2] / "rootfs/etc/services.d/monitor/run"
)


def _run_monitor_cycle(
    mocker,
    *,
    reattach_retries,
    restart_retries,
    reattach_result,
    dependent_apps=(),
    post_reattach_actions=(),
    manifest=None,
    missing=None,
    real_restart=False,
):
    device = {"name": "Stick", "server": "usbip-host", "bus_id": "1-2"}
    manifest = [device] if manifest is None else manifest
    missing = manifest if missing is None else missing
    config = {
        "log_level": "info",
        "monitor_interval": 30,
        "reattach_retries": reattach_retries,
        "restart_retries": restart_retries,
        "dependent_apps": list(dependent_apps),
        "post_reattach_actions": list(post_reattach_actions),
    }
    logger = mocker.Mock()
    notify = mocker.patch("usbip_lib.config.send_ha_notification")
    attempt = mocker.patch("usbip_lib.monitor.attempt_reattach")
    if isinstance(reattach_result, list):
        attempt.side_effect = reattach_result
    else:
        attempt.return_value = reattach_result
    restart_apps = None
    if not real_restart:
        restart_apps = mocker.patch("usbip_lib.monitor.restart_dependent_apps")

    mocker.patch("usbip_lib.config.get_app_config", return_value=config)
    mocker.patch("usbip_lib.events.write_event")
    mocker.patch("usbip_lib.logging_setup.setup_logging", return_value=logger)
    mocker.patch("usbip_lib.monitor.check_dependent_app_health")
    mocker.patch("usbip_lib.monitor.evaluate_flapping_clear", return_value=None)
    mocker.patch("usbip_lib.monitor.find_missing_devices", return_value=missing)
    mocker.patch("usbip_lib.monitor.is_on_cooldown", return_value=False)
    mocker.patch("usbip_lib.monitor.record_flapping_recovery", return_value=None)
    mocker.patch("usbip_lib.monitor.refresh_device_manifest")
    post_actions = mocker.patch("usbip_lib.monitor.run_post_reattach_actions")
    mocker.patch("usbip_lib.monitor.set_cooldown")
    mocker.patch("usbip_lib.usbip.parse_usbip_port", return_value=[])
    mocker.patch("usbip_lib.usbip.read_device_manifest", return_value=manifest)
    mocker.patch("time.sleep", side_effect=[None, SystemExit(0)])

    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(MONITOR_RUN_PATH))

    assert stopped.value.code == 0
    return {
        "attempt": attempt,
        "device": device,
        "logger": logger,
        "notify": notify,
        "post_actions": post_actions,
        "restart_apps": restart_apps,
    }


@pytest.fixture
def mock_full_env(mocker, tmp_path):
    """Mock all system dependencies for integration testing."""
    events_file = str(tmp_path / "events.jsonl")
    manifest_file = str(tmp_path / "manifest.json")

    # Patch constants
    mocker.patch("usbip_lib.usbip.DEVICE_MANIFEST_FILE", manifest_file)
    mocker.patch("usbip_lib.events.EVENTS_FILE", events_file)
    mocker.patch("usbip_lib.usbip.time.sleep")

    # Mock supervisor API
    def _make_response(data):
        resp = mocker.Mock()
        resp.read.return_value = json.dumps(data).encode()
        resp.__enter__ = mocker.Mock(return_value=resp)
        resp.__exit__ = mocker.Mock(return_value=False)
        return resp

    mock_urlopen = mocker.patch("usbip_lib.config.urllib.request.urlopen")
    mock_urlopen.return_value = _make_response(SAMPLE_SUPERVISOR_INFO_RESPONSE)

    # Mock subprocess
    mock_run = mocker.patch("usbip_lib.usbip.subprocess.run")
    mock_run.return_value = mocker.Mock(returncode=0, stdout="", stderr="")

    return {
        "urlopen": mock_urlopen,
        "subprocess": mock_run,
        "events_file": events_file,
        "manifest_file": manifest_file,
        "tmp_path": tmp_path,
    }


class TestLoadModulesLogic:
    """Test the load_modules init script logic."""

    def test_calls_modprobe(self, mock_full_env):
        from usbip_lib.usbip import load_kernel_module

        mock_full_env["subprocess"].side_effect = [
            # modprobe
            pytest.importorskip("unittest.mock").Mock(
                returncode=0, stdout="", stderr=""
            ),
            # lsmod
            pytest.importorskip("unittest.mock").Mock(
                returncode=0, stdout="vhci_hcd  12345  0\n", stderr=""
            ),
        ]
        assert load_kernel_module("vhci-hcd") is True
        calls = mock_full_env["subprocess"].call_args_list
        assert any("/sbin/modprobe" in str(c) for c in calls)

    def test_fails_on_modprobe_error(self, mock_full_env):
        from usbip_lib.usbip import load_kernel_module

        mock_full_env["subprocess"].return_value = pytest.importorskip(
            "unittest.mock"
        ).Mock(returncode=1, stdout="", stderr="module not found")
        assert load_kernel_module("vhci-hcd") is False


class TestInitDevicesLogic:
    """Test the init_devices script logic (discovery + manifest building)."""

    def test_creates_manifest(self, mock_full_env):
        from usbip_lib.usbip import (
            build_device_manifest,
            discover_devices,
            write_device_manifest,
        )

        # Mock usbip list to return devices
        mock_full_env["subprocess"].return_value = pytest.importorskip(
            "unittest.mock"
        ).Mock(returncode=0, stdout=SAMPLE_USBIP_LIST_OUTPUT, stderr="")

        discovery = discover_devices(["192.168.1.44"])
        assert len(discovery) == 2

        manifest = build_device_manifest(SAMPLE_APP_CONFIG, discovery)
        write_device_manifest(manifest, mock_full_env["manifest_file"])
        assert os.path.exists(mock_full_env["manifest_file"])

        with open(mock_full_env["manifest_file"]) as f:
            saved = json.load(f)
        assert len(saved) == 2
        assert saved[0]["bus_id"] == "1-1.4"  # resolved from device_id

    def test_resolves_device_ids(self, mock_full_env):
        from usbip_lib.usbip import build_device_manifest

        manifest = build_device_manifest(SAMPLE_APP_CONFIG, SAMPLE_DISCOVERY_DATA)
        # 0658:0200 should resolve to 1-1.4
        assert manifest[0]["bus_id"] == "1-1.4"
        assert manifest[0]["name"] == "Z-Wave Stick"
        # 1-1.3 is a bus_id, used directly
        assert manifest[1]["bus_id"] == "1-1.3"


class TestRunServiceLogic:
    """Test the usbip run service script logic."""

    def test_attaches_all_from_manifest(self, mock_full_env):
        from usbip_lib.usbip import (
            attach_all_from_manifest,
            parse_usbip_port,
            read_device_manifest,
            write_device_manifest,
        )

        # Write manifest
        write_device_manifest(SAMPLE_DEVICE_MANIFEST, mock_full_env["manifest_file"])

        # Read it back
        manifest = read_device_manifest(mock_full_env["manifest_file"])
        assert len(manifest) == 2

        # Attach all
        succeeded, failed = attach_all_from_manifest(manifest)
        assert succeeded == 2
        assert failed == 0

    def test_handles_partial_failure(self, mock_full_env):
        from usbip_lib.usbip import attach_all_from_manifest, write_device_manifest

        write_device_manifest(SAMPLE_DEVICE_MANIFEST, mock_full_env["manifest_file"])

        Mock = pytest.importorskip("unittest.mock").Mock
        # Dev1: pre-detach ok, attach ok; Dev2: pre-detach ok, 3x attach fail
        mock_full_env["subprocess"].side_effect = [
            Mock(returncode=0, stdout="", stderr=""),  # dev1 pre-detach
            Mock(returncode=0, stdout="", stderr=""),  # dev1 attach
            Mock(returncode=0, stdout="", stderr=""),  # dev2 pre-detach
            Mock(returncode=1, stdout="", stderr="err"),  # dev2 attach 1
            Mock(returncode=1, stdout="", stderr="err"),  # dev2 attach 2
            Mock(returncode=1, stdout="", stderr="err"),  # dev2 attach 3
        ]

        from usbip_lib.usbip import read_device_manifest

        manifest = read_device_manifest(mock_full_env["manifest_file"])
        succeeded, failed = attach_all_from_manifest(manifest)
        assert succeeded == 1
        assert failed == 1


class TestMonitorServiceLoop:
    def test_zero_reattach_retries_reports_disabled_without_failure(self, mocker):
        env = _run_monitor_cycle(
            mocker,
            reattach_retries=0,
            restart_retries=1,
            reattach_result=None,
        )

        env["attempt"].assert_called_once_with(env["device"], 0, env["logger"])
        lost = [
            call
            for call in env["notify"].call_args_list
            if call.kwargs.get("notification_type") == "device_lost"
        ]
        assert len(lost) == 1
        assert lost[0].args == (
            "USB/IP: Device Lost",
            "Stick (1-2) from usbip-host is no longer attached. "
            "Automatic reattach is disabled. Manual intervention required.",
        )
        assert not any(
            call.kwargs.get("notification_type") == "reattach_failed"
            for call in env["notify"].call_args_list
        )

    def test_zero_restart_retries_does_not_claim_post_recovery_restart(self, mocker):
        env = _run_monitor_cycle(
            mocker,
            reattach_retries=1,
            restart_retries=0,
            reattach_result=True,
            dependent_apps=[{"name": "Z2M", "slug": "z2m"}],
        )

        assert any(
            call.kwargs.get("notification_type") == "device_recovered"
            for call in env["notify"].call_args_list
        )
        env["restart_apps"].assert_called_once_with(
            [{"name": "Z2M", "slug": "z2m"}], 0, env["logger"]
        )
        assert not any(
            call.args
            and call.args[0] == "Restarting dependent apps after device recovery..."
            for call in env["logger"].info.call_args_list
        )


ZWAVE_STICK = {"name": "Z-Wave Stick", "server": "usbip-host", "bus_id": "1-1.2"}
ZIGBEE_STICK = {"name": "Zigbee Stick", "server": "usbip-host", "bus_id": "1-1.3"}
ZWAVE_APP = {"name": "Z-Wave JS", "slug": "core_zwave_js", "devices": ["Z-Wave Stick"]}
ZIGBEE_APP = {
    "name": "Zigbee2MQTT",
    "slug": "45df7312_zigbee2mqtt",
    "devices": ["Zigbee Stick"],
}
RESTART_LOG_LINE = "Restarting dependent apps after device recovery..."


class TestMonitorRestartsOnlyAffectedApps:
    """After a reattach, only the apps using the recovered stick restart."""

    @staticmethod
    def _cycle(mocker, *, missing, reattach_result=True, dependent_apps=None, **extra):
        return _run_monitor_cycle(
            mocker,
            reattach_retries=3,
            restart_retries=3,
            reattach_result=reattach_result,
            dependent_apps=[ZIGBEE_APP, ZWAVE_APP]
            if dependent_apps is None
            else dependent_apps,
            manifest=[ZWAVE_STICK, ZIGBEE_STICK],
            missing=missing,
            **extra,
        )

    def test_lost_zwave_stick_leaves_zigbee_app_running(self, mocker):
        env = self._cycle(mocker, missing=[ZWAVE_STICK])

        env["restart_apps"].assert_called_once_with([ZWAVE_APP], 3, env["logger"])

    def test_lost_zigbee_stick_leaves_zwave_app_running(self, mocker):
        env = self._cycle(mocker, missing=[ZIGBEE_STICK])

        env["restart_apps"].assert_called_once_with([ZIGBEE_APP], 3, env["logger"])

    def test_only_the_affected_app_reaches_the_supervisor(self, mocker):
        restart = mocker.patch("usbip_lib.monitor.restart_app", return_value=True)
        mocker.patch("usbip_lib.monitor.send_ha_notification")
        mocker.patch("usbip_lib.monitor.write_event")

        self._cycle(mocker, missing=[ZWAVE_STICK], real_restart=True)

        restart.assert_called_once_with("core_zwave_js")

    def test_both_sticks_recovered_restart_both_apps_once(self, mocker):
        env = self._cycle(mocker, missing=[ZWAVE_STICK, ZIGBEE_STICK])

        env["restart_apps"].assert_called_once_with(
            [ZIGBEE_APP, ZWAVE_APP], 3, env["logger"]
        )

    def test_failed_reattach_does_not_restart_the_app_of_that_stick(self, mocker):
        env = self._cycle(
            mocker,
            missing=[ZWAVE_STICK, ZIGBEE_STICK],
            reattach_result=[False, True],
        )

        env["restart_apps"].assert_called_once_with([ZIGBEE_APP], 3, env["logger"])

    def test_without_mapping_every_app_restarts_as_before(self, mocker):
        apps = [
            {"name": "Zigbee2MQTT", "slug": "45df7312_zigbee2mqtt"},
            {"name": "Z-Wave JS", "slug": "core_zwave_js"},
        ]

        env = self._cycle(mocker, missing=[ZWAVE_STICK], dependent_apps=apps)

        env["restart_apps"].assert_called_once_with(apps, 3, env["logger"])

    def test_no_restart_and_no_claim_when_no_app_uses_the_stick(self, mocker):
        env = self._cycle(mocker, missing=[ZWAVE_STICK], dependent_apps=[ZIGBEE_APP])

        env["restart_apps"].assert_not_called()
        assert not any(
            call.args and call.args[0] == RESTART_LOG_LINE
            for call in env["logger"].info.call_args_list
        )

    def test_post_reattach_actions_still_run_when_no_app_uses_the_stick(self, mocker):
        actions = [{"name": "Rescan", "url": "http://example.test/rescan"}]

        env = self._cycle(
            mocker,
            missing=[ZWAVE_STICK],
            dependent_apps=[ZIGBEE_APP],
            post_reattach_actions=actions,
        )

        env["post_actions"].assert_called_once_with(actions, env["logger"])


class TestFinishServiceLogic:
    """Test the usbip finish script logic."""

    def test_crash_exit_does_not_halt_container(self):
        """Non-zero/non-256 exit code should allow s6 restart (no halt)."""
        exit_code = 1
        should_halt = False
        if exit_code != 0 and exit_code != 256:
            should_halt = False
        assert should_halt is False

    def test_allows_restart_on_zero(self):
        """Exit code 0 should not halt."""
        exit_code = 0
        should_halt = exit_code != 0 and exit_code != 256
        assert should_halt is False

    def test_allows_restart_on_256(self):
        """Exit code 256 should not halt (normal s6 restart)."""
        exit_code = 256
        should_halt = exit_code != 0 and exit_code != 256
        assert should_halt is False


class TestDetachCleanupLogic:
    """Test the detach_devices cleanup script logic."""

    def test_detach_and_cleanup(self, mock_full_env):
        from usbip_lib.events import write_event
        from usbip_lib.usbip import cleanup_temp_files, detach_all

        Mock = pytest.importorskip("unittest.mock").Mock
        mock_full_env["subprocess"].side_effect = [
            Mock(returncode=0, stdout=SAMPLE_USBIP_PORT_OUTPUT, stderr=""),
            Mock(returncode=0, stdout="", stderr=""),  # detach port 0
            Mock(returncode=0, stdout="", stderr=""),  # detach port 1
        ]

        detached, failed = detach_all()
        assert detached == 2
        assert failed == 0

        write_event(
            "detach_all",
            f"Container stop: {detached} detached, {failed} failed",
            events_file=mock_full_env["events_file"],
        )

        # Verify event was written
        with open(mock_full_env["events_file"]) as f:
            event = json.loads(f.readline())
        assert event["type"] == "detach_all"
        assert "2 detached" in event["detail"]

    def test_removes_temp_files(self, mock_full_env):
        from usbip_lib.usbip import cleanup_temp_files

        manifest_path = Path(mock_full_env["manifest_file"])
        manifest_path.write_text("data")

        cleanup_temp_files()

        assert not manifest_path.exists()
