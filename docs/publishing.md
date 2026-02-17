# Publishing checklist (Home Assistant App Repository)

This project is distributed as a Home Assistant App repository.

## Scope

- Distribution target: Home Assistant App Store (custom repository)

## Pre-release checks

Run all checks from repository root using the project virtual environment:

```bash
.venv/bin/pre-commit run --all-files
PYTHONPATH=./rootfs/usr/local/lib .venv/bin/python -m pytest -q
.venv/bin/python scripts/check_version_consistency.py
```

## Versioning and metadata

- Keep versions aligned across:
  - `config.yaml`
  - `repository.yaml`
  - `CHANGELOG.md`
- Verify release automation assumptions in:
  - `.github/workflows/release.yml`
  - `scripts/release.py`

## Runtime validation in Home Assistant

```bash
ha apps stop local_ha_usbip_client
ha apps rebuild local_ha_usbip_client
ha apps start local_ha_usbip_client
ha apps logs local_ha_usbip_client --follow
```

Validate:

- App starts and stays running
- WebUI is reachable
- Attach/detach flow works
- Monitor re-attach flow works

## Release

- Create/publish GitHub release for the target version
- Ensure release notes reflect user-facing changes and migration notes (if any)
