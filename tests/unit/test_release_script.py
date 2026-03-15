"""Tests for the release helper script."""

import pytest

from scripts.release import validate_target_version


def test_validate_target_version_accepts_matching_repo_state():
    validate_target_version(
        "0.5.2-beta.7",
        {
            "config.yaml": "0.5.2-beta.7",
            "repository.yaml": "0.5.2-beta.7",
            "rootfs/usr/local/bin/webui/app.py": "0.5.2-beta.7",
        },
        "0.5.2-beta.7",
    )


def test_validate_target_version_rejects_internal_repo_mismatch():
    with pytest.raises(ValueError, match="Version mismatch detected in repository files"):
        validate_target_version(
            "0.5.2-beta.7",
            {
                "config.yaml": "0.5.2-beta.7",
                "repository.yaml": "0.5.2-beta.6",
                "rootfs/usr/local/bin/webui/app.py": "0.5.2-beta.7",
            },
            "0.5.2-beta.7",
        )


def test_validate_target_version_rejects_requested_version_mismatch():
    with pytest.raises(ValueError, match="does not match current repository version"):
        validate_target_version(
            "0.5.2-beta.7",
            {
                "config.yaml": "0.5.2-beta.6",
                "repository.yaml": "0.5.2-beta.6",
                "rootfs/usr/local/bin/webui/app.py": "0.5.2-beta.6",
            },
            "0.5.2-beta.7",
        )


def test_validate_target_version_rejects_changelog_mismatch():
    with pytest.raises(ValueError, match="Top versioned changelog section"):
        validate_target_version(
            "0.5.2-beta.7",
            {
                "config.yaml": "0.5.2-beta.7",
                "repository.yaml": "0.5.2-beta.7",
                "rootfs/usr/local/bin/webui/app.py": "0.5.2-beta.7",
            },
            "0.5.2-beta.8",
        )