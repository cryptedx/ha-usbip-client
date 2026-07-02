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


def test_dockerfile_installs_python_build_deps_temporarily():
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert "apk add --no-cache --virtual .build-deps" in dockerfile
    assert "build-base" in dockerfile
    assert "python3-dev" in dockerfile
    assert "apk del .build-deps" in dockerfile
