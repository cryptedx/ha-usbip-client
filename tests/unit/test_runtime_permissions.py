"""Static tests for app runtime permissions required by vhci-hcd loading."""

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config.yaml"
APPARMOR_PATH = REPO_ROOT / "apparmor.txt"
WEBUI_RUN_PATH = REPO_ROOT / "rootfs/etc/services.d/webui/run"


class TestConfigPermissions:
    def test_privileged_includes_sys_module(self):
        config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))

        assert "SYS_MODULE" in config["privileged"]
        assert "vhci-hcd" in config["kernel_modules"]

    def test_webui_uses_port_mapping_instead_of_host_network(self):
        config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))

        assert config["ingress"] is True
        assert config["ingress_port"] == 8099
        assert "host_network" not in config
        assert config["ports"] == {"8099/tcp": None}
        assert config["ports_description"] == {"8099/tcp": "Direct WebUI access"}


class TestWebUiRunScript:
    def test_logs_internal_port(self):
        run_script = WEBUI_RUN_PATH.read_text(encoding="utf-8")

        assert "internal port" in run_script
        assert "WEBUI_INTERNAL_PORT" in run_script


class TestAppArmorModuleAccess:
    def test_declares_sys_module_capability(self):
        profile = APPARMOR_PATH.read_text(encoding="utf-8")

        assert "capability sys_module," in profile

    def test_allows_module_metadata_paths(self):
        profile = APPARMOR_PATH.read_text(encoding="utf-8")

        for required_rule in [
            "/etc/modprobe.d/** r,",
            "/usr/lib/modprobe.d/** r,",
            "/run/modprobe.d/** r,",
            "/lib/modules/** r,",
            "/usr/lib/modules/** r,",
        ]:
            assert required_rule in profile
