#!/usr/bin/env python3
"""Validate that all release version fields are aligned."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG_PATH = ROOT / "CHANGELOG.md"
TEMPLATE_PATH = ROOT / "rootfs/usr/local/bin/webui/templates/index.html"

FILES_AND_PATTERNS = {
    ROOT / "config.yaml": r'^version:\s*"([^"]+)"\s*$',
    ROOT / "repository.yaml": r'^version:\s*"([^"]+)"\s*$',
    ROOT / "rootfs/usr/local/bin/webui/app.py": r'^APP_VERSION\s*=\s*"([^"]+)"\s*$',
}
VERSION_BUMP_REQUIRED_PATHS = {
    "CHANGELOG.md",
    "config.yaml",
    "repository.yaml",
    "rootfs/usr/local/bin/webui/app.py",
}
VERSION_BUMP_TRIGGER_FILES = {
    "Dockerfile",
    "apparmor.txt",
    "config.yaml",
    "requirements.txt",
}
VERSION_BUMP_TRIGGER_PREFIXES = ("rootfs/",)

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?$")
ASCII_VERSION_RE = re.compile(r"v(\d+\.\d+\.\d+(?:β)?)\s+│")


def extract_version(path: Path, pattern: str) -> str:
    text = path.read_text(encoding="utf-8")
    matches = re.findall(pattern, text, flags=re.MULTILINE)
    if len(matches) != 1:
        rel = path.relative_to(ROOT)
        raise ValueError(f"Expected exactly one version match in {rel}")
    return matches[0]


def to_ascii_version(version: str) -> str:
    if "-" in version:
        return version.split("-", 1)[0] + "β"
    return version


def extract_ascii_version(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    matches = ASCII_VERSION_RE.findall(text)
    if len(matches) != 1:
        rel = path.relative_to(ROOT)
        raise ValueError(f"Expected exactly one ASCII version token in {rel}")
    return matches[0]


def extract_latest_changelog_version(path: Path = CHANGELOG_PATH) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^## \[([^\]]+)\]", line)
        if not match:
            continue
        version = match.group(1).strip()
        if version.lower() == "unreleased":
            continue
        return version

    rel = path.relative_to(ROOT)
    raise ValueError(f"Expected at least one versioned changelog section in {rel}")


def extract_current_versions() -> dict[Path, str]:
    versions: dict[Path, str] = {}
    for path, pattern in FILES_AND_PATTERNS.items():
        version = extract_version(path, pattern)
        if not VERSION_RE.match(version):
            rel = path.relative_to(ROOT)
            raise ValueError(f"Invalid version format in {rel}: {version}")
        versions[path] = version
    return versions


def get_staged_paths() -> set[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def requires_version_bump(staged_paths: set[str]) -> bool:
    if not staged_paths:
        return False
    return any(
        path in VERSION_BUMP_TRIGGER_FILES
        or any(path.startswith(prefix) for prefix in VERSION_BUMP_TRIGGER_PREFIXES)
        for path in staged_paths
    )


def missing_version_bump_paths(staged_paths: set[str]) -> set[str]:
    if not requires_version_bump(staged_paths):
        return set()
    return VERSION_BUMP_REQUIRED_PATHS - staged_paths


def main() -> int:
    try:
        versions = extract_current_versions()

        unique_versions = set(versions.values())
        if len(unique_versions) != 1:
            print("Version mismatch detected:", file=sys.stderr)
            for path, version in versions.items():
                print(f"- {path.relative_to(ROOT)}: {version}", file=sys.stderr)
            return 1

        version = next(iter(unique_versions))
        expected_ascii = to_ascii_version(version)
        found_ascii = extract_ascii_version(TEMPLATE_PATH)
        if found_ascii != expected_ascii:
            rel = TEMPLATE_PATH.relative_to(ROOT)
            print(
                f"ASCII version mismatch in {rel}: expected v{expected_ascii}, found v{found_ascii}",
                file=sys.stderr,
            )
            return 1

        changelog_version = extract_latest_changelog_version(CHANGELOG_PATH)
        if not VERSION_RE.match(changelog_version):
            rel = CHANGELOG_PATH.relative_to(ROOT)
            raise ValueError(f"Invalid version format in {rel}: {changelog_version}")
        if changelog_version != version:
            rel = CHANGELOG_PATH.relative_to(ROOT)
            print(
                f"Changelog version mismatch in {rel}: expected {version}, found {changelog_version}",
                file=sys.stderr,
            )
            return 1

        missing_paths = missing_version_bump_paths(get_staged_paths())
        if missing_paths:
            print(
                "Release-affecting staged changes must include a version bump and matching changelog update in the same commit.",
                file=sys.stderr,
            )
            for path in sorted(missing_paths):
                print(f"- missing staged file: {path}", file=sys.stderr)
            return 1

        print(f"Version consistency check passed: {version}")
        return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
