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


def replace_once(
    path: Path, pattern: str, replacement: str, apply_changes: bool
) -> bool:
    original = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, original, flags=re.MULTILINE)
    if count != 1:
        raise ValueError(
            f"Expected exactly one match in {path.relative_to(ROOT)} for pattern: {pattern}"
        )
    if updated != original:
        if apply_changes:
            path.write_text(updated, encoding="utf-8")
        return True
    return False


def ensure_local_tag_absent(tag: str) -> None:
    result = run_git("tag", "--list", tag)
    if result.stdout.strip() == tag:
        raise ValueError(f"Tag already exists locally: {tag}")


def ensure_remote_tag_absent(tag: str) -> None:
    result = run_git("ls-remote", "--tags", "origin", tag)
    if result.stdout.strip():
        raise ValueError(f"Tag already exists on remote: {tag}")


def stage_release_files() -> None:
    # Stage all tracked modifications so code changes are not accidentally left out.
    run_git("add", "--update")
    # Explicitly stage version files in case any are new/untracked (e.g. fresh clone).
    run_git(
        "add",
        str(CONFIG_PATH.relative_to(ROOT)),
        str(REPOSITORY_PATH.relative_to(ROOT)),
        str(WEBUI_PATH.relative_to(ROOT)),
        str(TEMPLATE_PATH.relative_to(ROOT)),
        str(CHANGELOG_PATH.relative_to(ROOT)),
    )


def has_staged_changes() -> bool:
    result = run_git("diff", "--cached", "--quiet", check=False)
    return result.returncode != 0


def commit_release(version: str) -> bool:
    stage_release_files()
    if not has_staged_changes():
        return False
    run_git("commit", "-m", f"chore(release): {version}")
    return True


def create_tag(tag: str, version: str) -> None:
    run_git("tag", "-a", tag, "-m", f"Release {version}")


def push_release(branch: str, tag: str, commit_created: bool) -> None:
    if commit_created:
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
        assert_changelog_contains(version)
        ensure_local_tag_absent(tag)
        ensure_remote_tag_absent(tag)

        config_changed = replace_once(
            CONFIG_PATH,
            r'^version:\s*"[^"]+"\s*$',
            f'version: "{version}"',
            apply_changes=not args.dry_run,
        )
        repository_changed = replace_once(
            REPOSITORY_PATH,
            r'^version:\s*"[^"]+"\s*$',
            f'version: "{version}"',
            apply_changes=not args.dry_run,
        )
        webui_changed = replace_once(
            WEBUI_PATH,
            r'"version":\s*"[^"]+",',
            f'"version": "{version}",',
            apply_changes=not args.dry_run,
        )
        ascii_version = to_ascii_version(version)
        template_changed = replace_once(
            TEMPLATE_PATH,
            r"v\d+\.\d+\.\d+(?:β)?(\s+│)",
            rf"v{ascii_version}\1",
            apply_changes=not args.dry_run,
        )

        if args.dry_run:
            print(f"Dry-run successful for version: {version}")
            print(f"Tag candidate: {tag}")
            print(
                "Would update versions in: "
                + ", ".join(
                    [
                        name
                        for name, changed in [
                            (str(CONFIG_PATH.relative_to(ROOT)), config_changed),
                            (
                                str(REPOSITORY_PATH.relative_to(ROOT)),
                                repository_changed,
                            ),
                            (str(WEBUI_PATH.relative_to(ROOT)), webui_changed),
                            (str(TEMPLATE_PATH.relative_to(ROOT)), template_changed),
                        ]
                        if changed
                    ]
                )
                if any(
                    [
                        config_changed,
                        repository_changed,
                        webui_changed,
                        template_changed,
                    ]
                )
                else "No version file updates required (already at requested version)."
            )
            print("Would create commit: chore(release): " + version)
            print("Would create tag: " + tag)
            if args.push:
                print("Would push branch and tag to origin.")
            return 0

        commit_created = commit_release(version)
        create_tag(tag, version)

        if args.push:
            push_release(branch, tag, commit_created)

        print(f"Release prepared: {version}")
        print(f"Tag created: {tag}")
        if args.push:
            print("Pushed to origin.")
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
