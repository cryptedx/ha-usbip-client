#!/usr/bin/env python3
"""Create a versioned release commit and git tag for GitHub release automation."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.yaml"
REPOSITORY_PATH = ROOT / "repository.yaml"
WEBUI_PATH = ROOT / "rootfs/usr/local/bin/webui/app.py"
TEMPLATE_PATH = ROOT / "rootfs/usr/local/bin/webui/templates/index.html"
CHANGELOG_PATH = ROOT / "CHANGELOG.md"

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?$")
ASCII_VERSION_RE = re.compile(r"v(\d+\.\d+\.\d+(?:β)?)\s+│")
FILES_AND_PATTERNS = {
    CONFIG_PATH: r'^version:\s*"([^"]+)"\s*$',
    REPOSITORY_PATH: r'^version:\s*"([^"]+)"\s*$',
    WEBUI_PATH: r'^APP_VERSION\s*=\s*"([^"]+)"\s*$',
}


def to_ascii_version(version: str) -> str:
    if "-" in version:
        return version.split("-", 1)[0] + "β"
    return version


def run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=check,
    )


def current_branch() -> str:
    return run_git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def validate_branch(version: str, branch: str) -> None:
    prerelease = "-" in version
    if branch == "main" and prerelease:
        raise ValueError("Pre-release versions are not allowed on branch 'main'.")
    if branch == "dev" and not prerelease:
        raise ValueError("Stable versions are not allowed on branch 'dev'.")


def assert_changelog_contains(version: str) -> None:
    expected = f"## [{version}]"
    text = CHANGELOG_PATH.read_text(encoding="utf-8")
    if expected not in text:
        raise ValueError(
            f"Missing changelog section '{expected}' in {CHANGELOG_PATH.relative_to(ROOT)}"
        )


def extract_version(path: Path, pattern: str) -> str:
    matches = re.findall(pattern, path.read_text(encoding="utf-8"), flags=re.MULTILINE)
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one version match in {path.relative_to(ROOT)}"
        )
    return matches[0]


def extract_ascii_version(path: Path) -> str:
    matches = ASCII_VERSION_RE.findall(path.read_text(encoding="utf-8"))
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one ASCII version token in {path.relative_to(ROOT)}"
        )
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

    raise ValueError(
        f"Expected at least one versioned changelog section in {path.relative_to(ROOT)}"
    )


def extract_current_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for path, pattern in FILES_AND_PATTERNS.items():
        version = extract_version(path, pattern)
        if not VERSION_RE.match(version):
            raise ValueError(
                f"Invalid version format in {path.relative_to(ROOT)}: {version}"
            )
        versions[str(path.relative_to(ROOT))] = version
    return versions


def validate_target_version(
    version: str, current_versions: dict[str, str], changelog_version: str
) -> None:
    unique_versions = set(current_versions.values())
    if len(unique_versions) != 1:
        details = "\n".join(
            f"- {path}: {found_version}"
            for path, found_version in sorted(current_versions.items())
        )
        raise ValueError(f"Version mismatch detected in repository files:\n{details}")

    current_version = next(iter(unique_versions))
    if current_version != version:
        raise ValueError(
            "Requested version "
            f"{version} does not match current repository version {current_version}. "
            "Bump and commit the version before running release.py."
        )

    if changelog_version != version:
        raise ValueError(
            "Top versioned changelog section "
            f"{changelog_version} does not match requested version {version}."
        )


def assert_clean_worktree() -> None:
    unstaged = run_git("diff", "--quiet", check=False)
    if unstaged.returncode != 0:
        raise ValueError(
            "Working tree has unstaged changes. Commit or stash them before preparing a release."
        )

    staged = run_git("diff", "--cached", "--quiet", check=False)
    if staged.returncode != 0:
        raise ValueError(
            "Index has staged but uncommitted changes. Commit them before preparing a release."
        )


def ensure_local_tag_absent(tag: str) -> None:
    result = run_git("tag", "--list", tag)
    if result.stdout.strip() == tag:
        raise ValueError(f"Tag already exists locally: {tag}")


def ensure_remote_tag_absent(tag: str) -> None:
    result = run_git("ls-remote", "--tags", "origin", tag)
    if result.stdout.strip():
        raise ValueError(f"Tag already exists on remote: {tag}")


def create_tag(tag: str, version: str) -> None:
    run_git("tag", "-a", tag, "-m", f"Release {version}")


def push_release(branch: str, tag: str) -> None:
    run_git("push", "origin", branch)
    run_git("push", "origin", tag)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare and tag a release (GitHub Action creates the GitHub release)."
    )
    parser.add_argument(
        "version", help="Version without v-prefix, e.g. 0.5.1 or 0.5.1-beta.1"
    )
    parser.add_argument(
        "--push",
        action="store_true",
        help="Push branch (if committed) and tag to origin",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate release and preview changes without modifying files or creating git objects",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    version = args.version.strip()

    if not VERSION_RE.match(version):
        print(f"Invalid version format: {version}", file=sys.stderr)
        return 1

    tag = f"v{version}"

    try:
        branch = current_branch()
        validate_branch(version, branch)
        assert_clean_worktree()
        current_versions = extract_current_versions()
        changelog_version = extract_latest_changelog_version()
        validate_target_version(version, current_versions, changelog_version)

        found_ascii = extract_ascii_version(TEMPLATE_PATH)
        expected_ascii = to_ascii_version(version)
        if found_ascii != expected_ascii:
            raise ValueError(
                "ASCII version mismatch in "
                f"{TEMPLATE_PATH.relative_to(ROOT)}: expected v{expected_ascii}, found v{found_ascii}"
            )

        assert_changelog_contains(version)
        ensure_local_tag_absent(tag)
        ensure_remote_tag_absent(tag)

        if args.dry_run:
            print(f"Dry-run successful for version: {version}")
            print(f"Tag candidate: {tag}")
            print(
                "Validated current repository version in: config.yaml, repository.yaml, "
                "rootfs/usr/local/bin/webui/app.py, rootfs/usr/local/bin/webui/templates/index.html, CHANGELOG.md"
            )
            print("Would create tag: " + tag)
            if args.push:
                print("Would push branch and tag to origin.")
            return 0

        create_tag(tag, version)

        if args.push:
            push_release(branch, tag)

        print(f"Release prepared: {version}")
        print(f"Tag created: {tag}")
        if args.push:
            print("Pushed branch and tag to origin.")
        else:
            print(
                "Tag not pushed yet. Push with: git push origin HEAD && git push origin "
                + tag
            )

        return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        details = exc.stderr.strip() if exc.stderr else exc.stdout.strip()
        print(details or str(exc), file=sys.stderr)
        return exc.returncode or 1


if __name__ == "__main__":
    raise SystemExit(main())
