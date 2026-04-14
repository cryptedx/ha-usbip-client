"""Tests for Home Assistant build metadata."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE_PATH = ROOT / "Dockerfile"


def test_dockerfile_declares_home_assistant_base_image_directly():
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert "ARG BUILD_FROM" not in dockerfile
    assert "FROM ${BUILD_FROM}" not in dockerfile
    assert dockerfile.startswith("FROM ghcr.io/home-assistant/base:latest\n")
