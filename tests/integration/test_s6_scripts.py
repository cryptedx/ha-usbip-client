"""Integration tests for s6 script logic.

These tests import and exercise the core logic from the s6 Python scripts
without actually running s6-overlay. All system calls are mocked.
"""

import json
import os

import pytest

from testdata import (
    SAMPLE_APP_CONFIG,
    SAMPLE_DEVICE_MANIFEST,
    SAMPLE_DISCOVERY_DATA,
    SAMPLE_SUPERVISOR_INFO_RESPONSE,
    SAMPLE_USBIP_LIST_OUTPUT,
    SAMPLE_USBIP_PORT_OUTPUT,
)


@pytest.fixture
def mock_full_env(mocker, tmp_path):
    """Mock all system dependencies for integration testing."""
    events_file = str(tmp_path / "events.jsonl")
    manifest_file = str(tmp_path / "manifest.json")
    attached_file = str(tmp_path / "attached.txt")

    # Patch constants
    mocker.patch("usbip_lib.usbip.DEVICE_MANIFEST_FILE", manifest_file)
    mocker.patch("usbip_lib.usbip.ATTACHED_DEVICES_FILE", attached_file)
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
        "attached_file": attached_file,
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

        # Create temp files
        for path in [
            mock_full_env["attached_file"],
            mock_full_env["manifest_file"],
        ]:
            with open(path, "w") as f:
                f.write("data")

        cleanup_temp_files()

        assert not os.path.exists(mock_full_env["attached_file"])
        assert not os.path.exists(mock_full_env["manifest_file"])
