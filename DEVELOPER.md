# Developer Guide

This document contains development-focused information for the HA USB/IP Client project.

## Project Structure

- `rootfs/etc/cont-init.d/`: s6 init scripts (`load_modules.py`, `init_devices.py`)
- `rootfs/etc/services.d/`: long-running services (`usbip`, `monitor`, `webui`)
- `rootfs/etc/cont-finish.d/`: shutdown cleanup scripts (`detach_devices.py`)
- `rootfs/usr/local/lib/usbip_lib/`: shared Python library (`config`, `usbip`, `monitor`, `events`, `logging_setup`)
- `rootfs/usr/local/bin/webui/`: Flask + Socket.IO WebUI
- `tests/unit/` and `tests/integration/`: pytest test suites

## Local Development

1. Clone the repository and open it in VS Code.
1. Install development dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

1. Run tests:

```bash
PYTHONPATH=./rootfs/usr/local/lib pytest -q
```

1. Install and enable pre-commit hooks:

```bash
pre-commit install
```

1. Run all hooks manually (recommended before pushing):

```bash
pre-commit run --all-files
```

## Pre-commit Checks

The repository enforces these checks before each commit:

- `ruff` lint rules
- `ruff format --check`
- `yamllint` with `.yamllint.yaml`
- `pymarkdown` markdown linting
- `gitleaks` with `.gitleaks.toml`
- `scripts/check_version_consistency.py` to ensure version alignment in:
  - `config.yaml`
  - `repository.yaml`
  - `rootfs/usr/local/bin/webui/app.py`
- Full test suite: `PYTHONPATH=./rootfs/usr/local/lib pytest -q`

If you must bypass hooks temporarily, use `git commit --no-verify` only for local emergency work and follow up by running `pre-commit run --all-files` before pushing.

## Versioning Rules

Version values should stay aligned in:

- `config.yaml`
- `repository.yaml`
- `rootfs/usr/local/bin/webui/app.py` (template global `version`)

Changelog format follows Keep a Changelog style in `CHANGELOG.md`.

## Release Automation (Local + GitHub)

Release flow is tag-driven:

1. Prepare changelog section (`## [X.Y.Z]` or `## [X.Y.Z-beta.1]`).
1. Run local release helper:

```bash
./scripts/release.py 0.5.1-beta.1 --push
```

1. GitHub Actions workflow `.github/workflows/release.yml` creates the GitHub release from the pushed tag and publishes the matching section from `CHANGELOG.md` as the release notes.

### Branch and tag policy

- Tag format:
  - Stable: `vX.Y.Z`
  - Pre-release: `vX.Y.Z-beta.1`
- Branch constraints enforced by script:
  - `main`: stable only
  - `dev`: pre-release only

### Dry-run

Use dry-run to validate everything without changing files, creating commits, or tags:

```bash
./scripts/release.py 0.5.1-beta.1 --dry-run
```

## Contribution Notes

- Keep changes minimal and scoped.
- Add/adjust tests for changed behavior where practical.
- Use conventional commits (for example: `fix(monitor): handle missing devices`).
- Prefer shared logic inside `usbip_lib` over duplicating code across s6 scripts/WebUI.

## Operational Notes (Home Assistant)

When validating inside Home Assistant:

- Rebuild app after code changes.
- If `config.yaml` schema changes, uninstall/reinstall app for clean config migration.
- Verify logs and service status after restart.
