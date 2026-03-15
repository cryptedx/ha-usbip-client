"""Tests for the version consistency helper script."""

from pathlib import Path

from scripts.check_version_consistency import (
    CHANGELOG_PATH,
    FILES_AND_PATTERNS,
    ROOT,
    TEMPLATE_PATH,
    VERSION_BUMP_REQUIRED_PATHS,
    VERSION_RE,
    extract_ascii_version,
    extract_latest_changelog_version,
    extract_version,
    missing_version_bump_paths,
    to_ascii_version,
)


def test_repo_version_sources_stay_aligned():
    app_path = ROOT / "rootfs/usr/local/bin/webui/app.py"
    config_path = ROOT / "config.yaml"
    repository_path = ROOT / "repository.yaml"

    app_version = extract_version(app_path, FILES_AND_PATTERNS[app_path])
    config_version = extract_version(config_path, FILES_AND_PATTERNS[config_path])
    repository_version = extract_version(
        repository_path, FILES_AND_PATTERNS[repository_path]
    )

    assert VERSION_RE.match(app_version)
    assert app_version == config_version
    assert app_version == repository_version


def test_template_ascii_version_matches_repo_version():
    config_path = ROOT / "config.yaml"
    version = extract_version(config_path, FILES_AND_PATTERNS[config_path])

    assert extract_ascii_version(TEMPLATE_PATH) == to_ascii_version(version)


def test_top_versioned_changelog_matches_repo_version():
    config_path = ROOT / "config.yaml"
    version = extract_version(config_path, FILES_AND_PATTERNS[config_path])

    assert extract_latest_changelog_version(CHANGELOG_PATH) == version


def test_release_affecting_changes_require_version_bump_metadata():
    assert missing_version_bump_paths({"apparmor.txt"}) == VERSION_BUMP_REQUIRED_PATHS


def test_release_affecting_commit_passes_with_version_metadata():
    staged_paths = {
        "CHANGELOG.md",
        "config.yaml",
        "repository.yaml",
        "rootfs/etc/cont-init.d/load_modules.py",
        "rootfs/usr/local/bin/webui/app.py",
    }

    assert missing_version_bump_paths(staged_paths) == set()


def test_docs_only_changes_do_not_require_version_bump():
    assert (
        missing_version_bump_paths({"README.md", "tests/unit/test_usbip.py"}) == set()
    )


def test_root_points_to_repository_root():
    assert (ROOT / "config.yaml") == Path(__file__).resolve().parents[2] / "config.yaml"
