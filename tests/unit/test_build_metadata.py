"""Tests for Home Assistant build metadata."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE_PATH = ROOT / "Dockerfile"
REQUIREMENTS_PATH = ROOT / "requirements.txt"


def test_dockerfile_declares_home_assistant_base_image_directly():
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert "ARG BUILD_FROM" not in dockerfile
    assert "FROM ${BUILD_FROM}" not in dockerfile
    assert dockerfile.startswith("FROM ghcr.io/home-assistant/base:latest\n")


def test_gevent_pin_has_python_314_musllinux_wheels():
    requirements = REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines()

    assert "gevent==26.5.0" in requirements


def test_runtime_has_no_unused_socketio_dependencies():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    app_source = (ROOT / "rootfs/usr/local/bin/webui/app.py").read_text(
        encoding="utf-8"
    )

    assert "flask-socketio" not in requirements
    assert "gevent-websocket" not in requirements
    assert "SocketIO" not in app_source
    assert "WSGIServer" in app_source
    assert "app, log=None)" in app_source


def test_runtime_has_no_write_only_attached_device_file():
    runtime_paths = [
        ROOT / "rootfs/usr/local/lib/usbip_lib/constants.py",
        ROOT / "rootfs/usr/local/lib/usbip_lib/usbip.py",
        ROOT / "rootfs/etc/services.d/usbip/run",
    ]

    assert all(
        "ATTACHED_DEVICES_FILE" not in path.read_text(encoding="utf-8")
        for path in runtime_paths
    )


def test_package_init_has_no_eager_reexport_layer():
    package_init = (ROOT / "rootfs/usr/local/lib/usbip_lib/__init__.py").read_text(
        encoding="utf-8"
    )

    assert "__all__" not in package_init
    assert "from ." not in package_init


def test_dockerfile_installs_python_build_deps_temporarily():
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert "apk add --no-cache --virtual .build-deps" in dockerfile
    assert "build-base" in dockerfile
    assert "python3-dev" in dockerfile
    assert "apk del .build-deps" in dockerfile
