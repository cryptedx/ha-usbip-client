"""Tests for the version consistency helper script."""

from pathlib import Path

from scripts.check_version_consistency import FILES_AND_PATTERNS, ROOT, VERSION_RE, extract_version


def test_webui_version_comes_from_app_version_constant():
    app_path = ROOT / "rootfs/usr/local/bin/webui/app.py"
    config_path = ROOT / "config.yaml"

    app_version = extract_version(app_path, FILES_AND_PATTERNS[app_path])
    config_version = extract_version(config_path, FILES_AND_PATTERNS[config_path])

    assert VERSION_RE.match(app_version)
    assert app_version == config_version


def test_root_points_to_repository_root():
    assert (ROOT / "config.yaml") == Path(__file__).resolve().parents[2] / "config.yaml"
