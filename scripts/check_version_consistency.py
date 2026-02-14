#!/usr/bin/env python3
"""Validate that all release version fields are aligned."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FILES_AND_PATTERNS = {
    ROOT / "config.yaml": r'^version:\s*"([^"]+)"\s*$',
    ROOT / "repository.yaml": r'^version:\s*"([^"]+)"\s*$',
    ROOT / "rootfs/usr/local/bin/webui/app.py": r'"version":\s*"([^"]+)",',
}

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?$")


def extract_version(path: Path, pattern: str) -> str:
    text = path.read_text(encoding="utf-8")
    matches = re.findall(pattern, text, flags=re.MULTILINE)
    if len(matches) != 1:
        rel = path.relative_to(ROOT)
        raise ValueError(f"Expected exactly one version match in {rel}")
    return matches[0]


def main() -> int:
    versions: dict[Path, str] = {}
    try:
        for path, pattern in FILES_AND_PATTERNS.items():
            version = extract_version(path, pattern)
            if not VERSION_RE.match(version):
                rel = path.relative_to(ROOT)
                raise ValueError(f"Invalid version format in {rel}: {version}")
            versions[path] = version

        unique_versions = set(versions.values())
        if len(unique_versions) != 1:
            print("Version mismatch detected:", file=sys.stderr)
            for path, version in versions.items():
                print(f"- {path.relative_to(ROOT)}: {version}", file=sys.stderr)
            return 1

        version = next(iter(unique_versions))
        print(f"Version consistency check passed: {version}")
        return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
