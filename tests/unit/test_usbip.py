"""Unit tests for usbip_lib.usbip module."""

import subprocess

import pytest

from usbip_lib.usbip import (
    _parse_usbip_list_output,
    _parse_usbip_port_output,
    attach_all_from_manifest,
    attach_device,
    build_device_manifest,
    cleanup_temp_files,
    detach_all,
    detach_device,
    is_device_id,
    load_kernel_module,
    lookup_usb_name,
    read_device_manifest,
    resolve_device_id_to_bus_id,
    run_cmd,
    write_attached_devices_file,
    write_device_details_file,
    write_device_manifest,
)

from testdata import (
    SAMPLE_APP_CONFIG,
    SAMPLE_DEVICE_MANIFEST,
    SAMPLE_DISCOVERY_DATA,
    SAMPLE_USBIP_LIST_EMPTY,
    SAMPLE_USBIP_LIST_OUTPUT,
    SAMPLE_USBIP_PORT_EMPTY,
    SAMPLE_USBIP_PORT_OUTPUT,
    SAMPLE_USBIP_PORT_SINGLE,
)


# ---------------------------------------------------------------------------
# run_cmd
# ---------------------------------------------------------------------------
class TestRunCmd:
    def test_success(self, mocker):
        mocker.patch(
            "usbip_lib.usbip.subprocess.run",
            return_value=mocker.Mock(returncode=0, stdout="ok", stderr=""),
        )
        rc, out, err = run_cmd(["echo", "hello"])
        assert rc == 0
        assert out == "ok"

    def test_timeout(self, mocker):
        mocker.patch(
            "usbip_lib.usbip.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="test", timeout=5),
        )
        rc, out, err = run_cmd(["sleep", "999"], timeout=1)
        assert rc == -1
        assert err == "timeout"

    def test_exception(self, mocker):
        mocker.patch(
            "usbip_lib.usbip.subprocess.run",
            side_effect=FileNotFoundError("not found"),
        )
        rc, out, err = run_cmd(["nonexistent"])
        assert rc == -1
        assert "not found" in err


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
class TestParseUsbipPort:
    def test_empty(self):
        result = _parse_usbip_port_output(SAMPLE_USBIP_PORT_EMPTY)
        assert result == []

    def test_single_device(self):
        result = _parse_usbip_port_output(SAMPLE_USBIP_PORT_SINGLE)
        assert len(result) == 1
        d = result[0]
        assert d["port"] == 0
        assert d["status"] == "Port in Use"
        assert d["device_id"] == "0658:0200"
        assert d["server"] == "192.168.1.44"
        assert d["remote_busid"] == "1-1.4"

    def test_multiple_devices(self):
        result = _parse_usbip_port_output(SAMPLE_USBIP_PORT_OUTPUT)
        assert len(result) == 2
        assert result[0]["port"] == 0
        assert result[0]["device_id"] == "0658:0200"
        assert result[1]["port"] == 1
        assert result[1]["device_id"] == "10c4:ea60"

    def test_blank_input(self):
        result = _parse_usbip_port_output("")
        assert result == []


class TestParseUsbipList:
    def test_multiple_devices(self):
        result = _parse_usbip_list_output(SAMPLE_USBIP_LIST_OUTPUT, "192.168.1.44")
        assert len(result) == 2
        assert result[0]["busid"] == "1-1.3"
        assert result[0]["device_id"] == "10c4:ea60"
        assert result[0]["server"] == "192.168.1.44"
        assert "CP210x" in result[0]["name"]
        assert result[1]["busid"] == "1-1.4"
        assert result[1]["device_id"] == "0658:0200"

    def test_empty(self):
        result = _parse_usbip_list_output(SAMPLE_USBIP_LIST_EMPTY, "192.168.1.44")
        assert result == []

    def test_blank_input(self):
        result = _parse_usbip_list_output("", "192.168.1.44")
        assert result == []


class TestParseUsbipListCmd:
    def test_success(self, mocker):
        mocker.patch(
            "usbip_lib.usbip.run_cmd",
            return_value=(0, SAMPLE_USBIP_LIST_OUTPUT, ""),
        )
        from usbip_lib.usbip import parse_usbip_list

        result = parse_usbip_list("192.168.1.44")
        assert len(result) == 2

    def test_command_fails(self, mocker):
        mocker.patch(
            "usbip_lib.usbip.run_cmd",
            return_value=(1, "", "error"),
        )
        from usbip_lib.usbip import parse_usbip_list

        result = parse_usbip_list("192.168.1.44")
        assert result == []


# ---------------------------------------------------------------------------
# Device ID helpers
# ---------------------------------------------------------------------------
class TestIsDeviceId:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("0658:0200", True),
            ("10c4:ea60", True),
            ("ABCD:1234", True),
            ("abcd:ef01", True),
            ("1-1.4", False),
            ("1-1.3.2", False),
            ("0658:020", False),  # too short
            ("0658:02000", False),  # too long
            ("", False),
            ("0658-0200", False),
            ("xxxx:yyyy", False),
        ],
    )
    def test_is_device_id(self, value, expected):
        assert is_device_id(value) == expected


class TestResolveDeviceId:
    def test_found(self):
        result = resolve_device_id_to_bus_id(
            "192.168.1.44", "0658:0200", SAMPLE_DISCOVERY_DATA
        )
        assert result == "1-1.4"

    def test_not_found(self):
        result = resolve_device_id_to_bus_id(
            "192.168.1.44", "ffff:ffff", SAMPLE_DISCOVERY_DATA
        )
        assert result is None

    def test_wrong_server(self):
        result = resolve_device_id_to_bus_id(
            "10.0.0.1", "0658:0200", SAMPLE_DISCOVERY_DATA
        )
        assert result is None

    def test_empty_discovery(self):
        result = resolve_device_id_to_bus_id("192.168.1.44", "0658:0200", [])
        assert result is None


# ---------------------------------------------------------------------------
# USB name lookup
# ---------------------------------------------------------------------------
class TestLookupUsbName:
    def test_missing_file(self, tmp_path):
        result = lookup_usb_name("0658:0200", str(tmp_path / "nonexistent"))
        assert result == "0658:0200"

    def test_invalid_format(self, tmp_path):
        f = tmp_path / "usb.ids"
        f.write_text("")
        assert lookup_usb_name("invalid", str(f)) == "invalid"

    def test_vendor_found(self, tmp_path):
        f = tmp_path / "usb.ids"
        f.write_text("0658  Sigma Designs, Inc.\n\t0200  Z-Wave Stick\n")
        result = lookup_usb_name("0658:0200", str(f))
        assert "Sigma Designs" in result
        assert "Z-Wave Stick" in result

    def test_vendor_only(self, tmp_path):
        f = tmp_path / "usb.ids"
        f.write_text("0658  Sigma Designs, Inc.\n0659  Other\n")
        result = lookup_usb_name("0658:ffff", str(f))
        assert result == "Sigma Designs, Inc."


# ---------------------------------------------------------------------------
# Kernel module
# ---------------------------------------------------------------------------
class TestLoadKernelModule:
    def test_success(self, mocker):
        mock_run = mocker.patch("usbip_lib.usbip.subprocess.run")
        # modprobe succeeds
        mock_run.side_effect = [
            mocker.Mock(returncode=0, stdout="", stderr=""),
            mocker.Mock(returncode=0, stdout="vhci_hcd  12345  0\n", stderr=""),
        ]
        assert load_kernel_module("vhci-hcd") is True

    def test_failure(self, mocker):
        mock_run = mocker.patch("usbip_lib.usbip.subprocess.run")
        mock_run.return_value = mocker.Mock(
            returncode=1, stdout="", stderr="module not found"
        )
        assert load_kernel_module("vhci-hcd") is False

    def test_lsmod_fails_but_modprobe_ok(self, mocker):
        mock_run = mocker.patch("usbip_lib.usbip.subprocess.run")
        # modprobe succeeds, lsmod fails
        mock_run.side_effect = [
            mocker.Mock(returncode=0, stdout="", stderr=""),
            mocker.Mock(returncode=1, stdout="", stderr="lsmod error"),
        ]
        # Should still return True since modprobe succeeded
        assert load_kernel_module("vhci-hcd") is True


# ---------------------------------------------------------------------------
# Attach / Detach
# ---------------------------------------------------------------------------
class TestAttachDevice:
    def test_success_first_try(self, mocker):
        mocker.patch("usbip_lib.usbip.time.sleep")
        mock_run = mocker.patch("usbip_lib.usbip.subprocess.run")
        mock_run.return_value = mocker.Mock(returncode=0, stdout="", stderr="")
        assert attach_device("192.168.1.44", "1-1.4", "Test Device") is True

    def test_retry_then_success(self, mocker):
        mocker.patch("usbip_lib.usbip.time.sleep")
        mock_run = mocker.patch("usbip_lib.usbip.subprocess.run")
        # Pre-detach succeeds, first attach fails, second succeeds
        mock_run.side_effect = [
            mocker.Mock(returncode=0, stdout="", stderr=""),  # pre-detach
            mocker.Mock(returncode=1, stdout="", stderr="busy"),  # attach fail
            mocker.Mock(returncode=0, stdout="", stderr=""),  # attach success
        ]
        assert attach_device("192.168.1.44", "1-1.4", retries=2, delay=0) is True

    def test_all_retries_fail(self, mocker):
        mocker.patch("usbip_lib.usbip.time.sleep")
        mock_run = mocker.patch("usbip_lib.usbip.subprocess.run")
        mock_run.return_value = mocker.Mock(returncode=1, stdout="", stderr="error")
        assert attach_device("192.168.1.44", "1-1.4", retries=2, delay=0) is False


class TestDetachDevice:
    def test_success(self, mocker):
        mock_run = mocker.patch("usbip_lib.usbip.subprocess.run")
        mock_run.return_value = mocker.Mock(returncode=0, stdout="", stderr="")
        assert detach_device(0) is True

    def test_failure(self, mocker):
        mock_run = mocker.patch("usbip_lib.usbip.subprocess.run")
        mock_run.return_value = mocker.Mock(returncode=1, stdout="", stderr="err")
        assert detach_device(0) is False


class TestDetachAll:
    def test_with_ports(self, mocker):
        mocker.patch("usbip_lib.usbip.time.sleep")
        mock_run = mocker.patch("usbip_lib.usbip.subprocess.run")
        # usbip port returns data, then two successful detaches
        mock_run.side_effect = [
            mocker.Mock(returncode=0, stdout=SAMPLE_USBIP_PORT_OUTPUT, stderr=""),
            mocker.Mock(returncode=0, stdout="", stderr=""),  # detach port 0
            mocker.Mock(returncode=0, stdout="", stderr=""),  # detach port 1
        ]
        detached, failed = detach_all()
        assert detached == 2
        assert failed == 0

    def test_blind_fallback(self, mocker):
        mocker.patch("usbip_lib.usbip.time.sleep")
        mock_run = mocker.patch("usbip_lib.usbip.subprocess.run")
        # usbip port fails, then blind detach — some succeed
        returns = [mocker.Mock(returncode=1, stdout="", stderr="fail")]
        # ports 0-15: let 0 and 1 succeed
        for i in range(16):
            rc = 0 if i < 2 else 1
            returns.append(mocker.Mock(returncode=rc, stdout="", stderr=""))
        mock_run.side_effect = returns
        detached, failed = detach_all()
        assert detached == 2
        assert failed == 0

    def test_no_devices(self, mocker):
        mocker.patch("usbip_lib.usbip.time.sleep")
        mock_run = mocker.patch("usbip_lib.usbip.subprocess.run")
        mock_run.return_value = mocker.Mock(
            returncode=0, stdout=SAMPLE_USBIP_PORT_EMPTY, stderr=""
        )
        detached, failed = detach_all()
        assert detached == 0
        assert failed == 0


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------
class TestBuildDeviceManifest:
    def test_with_device_ids(self):
        manifest = build_device_manifest(SAMPLE_APP_CONFIG, SAMPLE_DISCOVERY_DATA)
        assert len(manifest) == 2
        # First device uses device_id, should resolve to bus_id
        assert manifest[0]["bus_id"] == "1-1.4"
        assert manifest[0]["name"] == "Z-Wave Stick"
        # Second device uses bus_id directly
        assert manifest[1]["bus_id"] == "1-1.3"
        assert manifest[1]["name"] == "Zigbee Stick"

    def test_device_id_not_found(self):
        config = {
            "usbipd_server_address": "192.168.1.44",
            "attach_delay": 2,
            "devices": [{"name": "Missing", "device_or_bus_id": "ffff:ffff"}],
        }
        manifest = build_device_manifest(config, SAMPLE_DISCOVERY_DATA)
        assert len(manifest) == 0

    def test_empty_devices(self):
        config = {
            "usbipd_server_address": "192.168.1.44",
            "devices": [],
        }
        manifest = build_device_manifest(config, SAMPLE_DISCOVERY_DATA)
        assert manifest == []

    def test_skip_empty_bus_id(self):
        config = {
            "usbipd_server_address": "192.168.1.44",
            "devices": [{"name": "Empty", "device_or_bus_id": ""}],
        }
        manifest = build_device_manifest(config, [])
        assert manifest == []


class TestManifestIO:
    def test_write_and_read(self, tmp_manifest_file):
        write_device_manifest(SAMPLE_DEVICE_MANIFEST, tmp_manifest_file)
        result = read_device_manifest(tmp_manifest_file)
        assert result == SAMPLE_DEVICE_MANIFEST

    def test_read_missing_file(self, tmp_path):
        result = read_device_manifest(str(tmp_path / "nonexistent.json"))
        assert result == []

    def test_read_invalid_json(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not json")
        result = read_device_manifest(str(f))
        assert result == []


class TestAttachAllFromManifest:
    def test_all_succeed(self, mocker):
        mocker.patch("usbip_lib.usbip.time.sleep")
        mock_run = mocker.patch("usbip_lib.usbip.subprocess.run")
        mock_run.return_value = mocker.Mock(returncode=0, stdout="", stderr="")
        succeeded, failed = attach_all_from_manifest(SAMPLE_DEVICE_MANIFEST)
        assert succeeded == 2
        assert failed == 0

    def test_partial_failure(self, mocker):
        mocker.patch("usbip_lib.usbip.time.sleep")
        mock_run = mocker.patch("usbip_lib.usbip.subprocess.run")
        # Dev 1: pre-detach ok, attach ok; Dev 2: pre-detach ok, 3 attach fails
        mock_run.side_effect = [
            mocker.Mock(returncode=0, stdout="", stderr=""),  # dev1 pre-detach
            mocker.Mock(returncode=0, stdout="", stderr=""),  # dev1 attach
            mocker.Mock(returncode=0, stdout="", stderr=""),  # dev2 pre-detach
            mocker.Mock(returncode=1, stdout="", stderr="err"),  # dev2 attach 1
            mocker.Mock(returncode=1, stdout="", stderr="err"),  # dev2 attach 2
            mocker.Mock(returncode=1, stdout="", stderr="err"),  # dev2 attach 3
        ]
        succeeded, failed = attach_all_from_manifest(SAMPLE_DEVICE_MANIFEST)
        assert succeeded == 1
        assert failed == 1

    def test_empty_manifest(self, mocker):
        succeeded, failed = attach_all_from_manifest([])
        assert succeeded == 0
        assert failed == 0


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------
class TestWriteDeviceDetailsFile:
    def test_write(self, tmp_details_file):
        write_device_details_file(SAMPLE_DISCOVERY_DATA, tmp_details_file)
        with open(tmp_details_file) as f:
            lines = f.readlines()
        assert len(lines) == 2
        assert "192.168.1.44|1-1.3|" in lines[0]
        assert "10c4:ea60" in lines[0]


class TestWriteAttachedDevicesFile:
    def test_write(self, tmp_attached_file):
        write_attached_devices_file([0, 1, 2], tmp_attached_file)
        with open(tmp_attached_file) as f:
            lines = f.read().strip().split("\n")
        assert lines == ["0", "1", "2"]


class TestCleanupTempFiles:
    def test_removes_files(self, tmp_path, mocker):
        # Create temp files
        for name in [
            "attached_devices.txt",
            "device_details.txt",
            "device_manifest.json",
        ]:
            (tmp_path / name).write_text("data")

        mocker.patch(
            "usbip_lib.usbip.ATTACHED_DEVICES_FILE",
            str(tmp_path / "attached_devices.txt"),
        )
        mocker.patch(
            "usbip_lib.usbip.DEVICE_DETAILS_FILE",
            str(tmp_path / "device_details.txt"),
        )
        mocker.patch(
            "usbip_lib.usbip.DEVICE_MANIFEST_FILE",
            str(tmp_path / "device_manifest.json"),
        )
        cleanup_temp_files()
        assert not (tmp_path / "attached_devices.txt").exists()
        assert not (tmp_path / "device_details.txt").exists()
        assert not (tmp_path / "device_manifest.json").exists()

    def test_missing_files_no_error(self, mocker):
        mocker.patch("usbip_lib.usbip.ATTACHED_DEVICES_FILE", "/nonexistent/a")
        mocker.patch("usbip_lib.usbip.DEVICE_DETAILS_FILE", "/nonexistent/b")
        mocker.patch("usbip_lib.usbip.DEVICE_MANIFEST_FILE", "/nonexistent/c")
        cleanup_temp_files()  # Should not raise
