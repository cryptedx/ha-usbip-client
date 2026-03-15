# Developer Guide

This document contains development-focused information for the HA USB/IP Client project.

## Operator Quick Flow

For any code change, follow this minimal sequence:

1. Classify impact (`config.yaml`, USB/IP core, monitor, s6 lifecycle, WebUI/API).
2. Implement the smallest correct fix and update tests for touched behavior.
3. Run targeted checks, then full local gates via `.venv`.
4. Run HA runtime validation (`stop` → `rebuild` → `start` → `info` → `logs`).
5. If `config.yaml` schema changed, run uninstall/install before concluding validation.
6. Hand off with risks, checks run, runtime evidence, and open issues.

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

1. Run targeted tests first, then full tests through `.venv`:

```bash
PYTHONPATH=./rootfs/usr/local/lib .venv/bin/python -m pytest -q
```

1. Install and enable pre-commit hooks:

```bash
.venv/bin/pre-commit install
```

1. Run all hooks manually (recommended before pushing):

```bash
.venv/bin/pre-commit run --all-files
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
  - `rootfs/usr/local/bin/webui/templates/index.html`
  - first versioned section in `CHANGELOG.md`
- Full test suite: `PYTHONPATH=./rootfs/usr/local/lib .venv/bin/python -m pytest -q`

For release-affecting commits on `dev`, the same hook also requires the version bump metadata (`config.yaml`, `repository.yaml`, `rootfs/usr/local/bin/webui/app.py`, `CHANGELOG.md`) to be staged in the same commit.

If you must bypass hooks temporarily, use `git commit --no-verify` only for local emergency work and follow up by running `.venv/bin/pre-commit run --all-files` before pushing.

## Versioning Rules

Version values should stay aligned in:

- `config.yaml`
- `repository.yaml`
- `rootfs/usr/local/bin/webui/app.py` (template global `version`)
- `rootfs/usr/local/bin/webui/templates/index.html` (ASCII header token)

Changelog format follows Keep a Changelog style in `CHANGELOG.md`.

On `dev`, release-affecting fixes are expected to bump the prerelease version and update the matching versioned changelog section in the same commit. `scripts/release.py` validates and tags that already versioned commit; it does not rewrite version files or create a separate release commit.

## Release Automation (Local + GitHub)

Release flow is tag-driven:

1. Prepare and commit the release-ready version bump across `config.yaml`, `repository.yaml`, `rootfs/usr/local/bin/webui/app.py`, and the matching changelog section (`## [X.Y.Z]` or `## [X.Y.Z-beta.1]`).
1. Run local release helper from a clean worktree:

```bash
./scripts/release.py 0.5.1-beta.1 --push
```

1. GitHub Actions workflow `.github/workflows/release.yml` creates the GitHub release from the pushed tag and publishes the matching section from `CHANGELOG.md` as the release notes.

The helper validates that the committed repository state already matches the requested version, then creates the tag and optionally pushes branch plus tag.

### Branch and tag policy

- Tag format:
  - Stable: `vX.Y.Z`
  - Pre-release: `vX.Y.Z-beta.1`
- Branch constraints enforced by script:
  - `main`: stable only
  - `dev`: pre-release only

### Dry-run

Use dry-run to validate branch, version, changelog, and tag state without creating tags or pushing:

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

- Runtime validation is required after every code change.
- Use targeted checks first, then full local quality gates, then runtime runbook.
- If `config.yaml` schema changes, uninstall/reinstall app for clean config migration.
- Verify logs and service status after restart.

### Runtime validation runbook (HA CLI)

Use the current `ha apps` commands (legacy addon command variants are deprecated):

```bash
ha apps stop local_ha_usbip_client
ha apps rebuild local_ha_usbip_client
ha apps start local_ha_usbip_client
ha apps info local_ha_usbip_client | grep '^state:'
ha apps logs local_ha_usbip_client --follow
```

Required local quality gates before runtime validation:

```bash
.venv/bin/pre-commit run --all-files
PYTHONPATH=./rootfs/usr/local/lib .venv/bin/python -m pytest -q
.venv/bin/python scripts/check_version_consistency.py
```

If schema fields in `config.yaml` changed, apply a clean reinstall:

```bash
ha apps uninstall local_ha_usbip_client
ha apps install local_ha_usbip_client
```
