"""Static tests for app runtime permissions required by vhci-hcd loading."""

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config.yaml"
APPARMOR_PATH = REPO_ROOT / "apparmor.txt"
WEBUI_RUN_PATH = REPO_ROOT / "rootfs/etc/services.d/webui/run"
WEBUI_APP_PATH = REPO_ROOT / "rootfs/usr/local/bin/webui/app.py"


class TestConfigPermissions:
    def test_privileged_includes_sys_module(self):
        config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))

        assert "SYS_MODULE" in config["privileged"]
        assert "vhci-hcd" in config["kernel_modules"]

    def test_webui_is_ingress_only(self):
        config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))

        assert config["ingress"] is True
        assert config["ingress_port"] == 8099
        assert "host_network" not in config
        assert "ports" not in config
        assert "ports_description" not in config


class TestWebUiRunScript:
    def test_serving_interpreter_initializes_logging_before_threads(self):
        app_source = WEBUI_APP_PATH.read_text(encoding="utf-8")
        main_source = app_source.split('if __name__ == "__main__":', 1)[1]

        setup_call = 'logger = setup_logging("info", name="webui")'
        startup_message = "Starting WebUI service on internal port %s..."

        assert "from usbip_lib.logging_setup import setup_logging" in app_source
        assert setup_call in main_source
        assert startup_message in main_source
        assert main_source.index(setup_call) < main_source.index("threading.Thread")

    def test_exec_wrapper_does_not_configure_discarded_logging_state(self):
        run_script = WEBUI_RUN_PATH.read_text(encoding="utf-8")

        assert "setup_logging" not in run_script
        assert "WEBUI_INTERNAL_PORT" not in run_script
        assert "os.execvp" in run_script


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
