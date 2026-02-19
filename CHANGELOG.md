# Changelog

## [Unreleased]

## [0.5.2-beta.6] - 2026-02-19

### Changed

- **Refactor: monitor retry logic**: Deduplicated identical restart-retry loops in `monitor.py` into a single `_retry_restart()` helper; added `clear_app_health_state()` export for test isolation.
- **Refactor: server collection**: Centralized USB/IP server discovery into `get_unique_servers()` in `config.py`; used in `init_devices.py` and WebUI health checker, replacing scattered manual loops.
- **Refactor: WebUI attach/detach**: Routed `api_attach()` and `api_detach()` through `usbip_lib` library functions (`attach_device`, `detach_device`, `is_device_id`, `resolve_device_id_to_bus_id`) instead of direct subprocess calls.
- **Refactor: constants**: Moved `HEALTH_INTERVAL_SECONDS` and all flapping thresholds (`COOLDOWN_SECONDS`, `FLAP_WINDOW_SECONDS`, `FLAP_WARNING_THRESHOLD`, `FLAP_CRITICAL_THRESHOLD`, `FLAP_CLEAR_STABLE_SECONDS`) to `constants.py`; removed local redefinitions in `monitor.py` and `app.py`.
- **Refactor: logging init**: Standardized `detach_devices.py` and `services.d/webui/run` to use `setup_logging()` from `usbip_lib.logging_setup`.
- **Refactor: normalization**: Removed redundant `normalize_notification_config()` and `normalize_dependent_apps_config()` calls from `send_ha_notification()`, `api_config_get()`, and `api_app_health()`; normalization already occurs at `get_app_config()` read time.
- **Refactor: relative imports**: Fixed `latency_history.py` to use package-relative imports (`from .constants`, `from .events`).

### Removed

- **Dead code**: Removed `write_device_details_file()` and its associated `DEVICE_DETAILS_FILE` constant from the public API; the legacy pipe-delimited details file is no longer written.

## [0.5.2-beta.5] - 2026-02-18

### Removed

- **32-Bit Architecture Support (BREAKING)**: Dropped `armhf`, `armv7`, and `i386` architectures following Home Assistant's official deprecation timeline (unsupported since 2025.12). Users on 32-bit systems must migrate to 64-bit-compatible hardware. Supported architectures are now `aarch64` and `amd64`.

## [0.5.2-beta.4] - 2026-02-17

### Changed

- **Publishing Clarity**: Documented that this project is distributed as a Home Assistant App repository.
- **Release Runbook**: Added a dedicated app publishing checklist with required local quality gates and Home Assistant runtime validation steps.

## [0.5.2-beta.3] - 2026-02-17

### Changed

- **Security Defaults**: Enabled AppArmor by default and aligned the profile with actual app runtime paths and Python services.
- **Privilege Hardening**: Removed `full_access` and switched to explicit USB/device mappings (`usb` plus `/dev/vhci`) with required capabilities only.
- **API Permissions**: Enabled `homeassistant_api` so notification calls to `/core/api` are authorized and Supervisor permission warnings are reduced.
- **Service Resilience**: Updated usbip finish handling to prefer automatic s6 restart behavior instead of halting the full container on transient usbip failures.
- **WebUI (Ingress compatibility)**: Themed custom scrollbar; added internal scroll container so Home Assistant Ingress shows the app scrollbar; added cache-busting for `style.css`; removed debug marker; updated related tests.
- **Config UX**: Added a two-step confirmation restart action in the Config tab (`↻ RESTART APP`) to apply saved settings.

### Fixed

- **Notification Settings Persistence**: Config save now verifies notification preferences (`notifications_enabled`, `notification_types`) were actually persisted and returns a clear API/UI error when Supervisor rejects schema fields.

### Added

- **Dashboard Diagnostics**: Added a compact first-run diagnostics panel in the WebUI Dashboard (module loaded, usbip availability, server reachability, discoverable devices).
- **Actionable API Errors**: Improved USB/IP attach/detach error messages with user-facing guidance for common causes (network, timeout, missing device, permissions).
- **Restart API Endpoint**: Added `POST /api/system/restart` to trigger app restart via Supervisor, including integration tests for success and failure paths.

## [0.5.2-beta.2] - 2026-02-14

### Changed

- **Terminology Migration**: Renamed remaining internal and user-facing legacy naming to "app/apps" across WebUI, docs, and service logs.
- **Config Key Rename**: Updated the legacy dependent service key to `dependent_apps` in schema, backend, frontend, and monitor service.
- **WebUI API Rename**: Renamed dependent app management endpoints to `/api/apps`, `/api/app-health`, `/api/app-restart`, and `/api/dependent-apps`.
- **Compatibility Note**: Kept required Home Assistant Supervisor API paths (`/addons/...`) and temporary legacy-key migration handling for existing configurations.

### Fixed

- **Consistency Alignment**: Updated tests and fixtures to match renamed app terminology and new API/config names.

## [0.5.1-beta.1] - 2026-02-14

### Added

- **Pre-commit Quality Gates**: Added repository-wide pre-commit hooks for linting, formatting, secret scanning, markdown checks, and full test execution.
- **Version Consistency Check**: Added `scripts/check_version_consistency.py` to ensure release version alignment across `config.yaml`, `repository.yaml`, and WebUI version metadata.
- **Developer Workflow Documentation**: Added explicit pre-commit setup and usage guidance in `DEVELOPER.md`.

### Changed

- **GitHub Release Notes Workflow**: Release notes are now extracted from the matching section in `CHANGELOG.md` and published directly in GitHub Releases.
- **Dev Tooling**: Updated `requirements-dev.txt` with current versions of `pytest`, `pytest-mock`, `pytest-cov`, `pre-commit`, `ruff`, and `yamllint`.
- **Lint/Format Baseline**: Applied Ruff-driven formatting and minor lint fixes in tests and Python modules to make full-repository checks pass.

### Fixed

- **Release Notes Quality**: Prevented empty auto-generated release descriptions by enforcing changelog-backed release bodies.

## [0.5.0-beta] - 2026-02-11

### Added

- **USB Device Monitoring**: Continuous monitoring of attached USB devices with automatic reattachment on failure.
  - Configurable `monitor_interval` (10-300s, default 30s) for health check frequency.
  - Configurable `reattach_retries` (0-10, default 3) for device reattachment attempts.
  - Cooldown period (5 minutes) between failure notifications to prevent spam.
  - Home Assistant notifications on device loss and recovery.
- **Dependent App Health Monitoring**: Monitors health of dependent apps and restarts them if they enter error state.
  - Configurable `dependent_apps` list with `name` and `slug` for each app.
  - Configurable `restart_retries` (0-10, default 3) for app restart attempts.
  - Automatic restart of failed apps (e.g., Zigbee2MQTT, Z-Wave JS) with notifications.
  - State change tracking to avoid repeated alerts for ongoing issues.
- **Enhanced Monitor Service**: New s6 service (`monitor/run`) for background device and app health monitoring.
  - Runs every `monitor_interval` seconds, checking device attachment and app states.
  - Integrates with existing event logging and notification systems.
- **Improved Error Handling**: Better handling of Supervisor API errors and device attachment failures.
- **Test Coverage**: Increased test coverage to 93% (from 88%) with additional unit tests for error paths.

### Changed

- **Version Bump**: Updated to 0.5.0-beta to reflect new monitoring capabilities.
- **README Updates**: Added documentation for new configuration options and features.
- **Monitor Integration**: WebUI now displays dependent app health status and allows selection from discovered apps.

### Fixed

- **Dependent App Restart**: Fixed issue where apps in error state were not automatically restarted. Now properly detects error states and attempts restart with retry logic.

**Summary of fixes**

| Severity | Count | Key points |
|---|---:|---|
| **Critical** | 2 | Duplicate test class (duplicate tests removed); SIGTERM was swallowed (services now correctly handle SIGTERM) |
| **High** | 4 | Missing API authentication; version inconsistency between components; monitor module not unit-testable; misconfigured CORS* |
| **Medium** | 10 | Fixed log de-duplication bug; various race conditions resolved; added missing tests; removed unnecessary Linux capabilities |
| **Low** | 8+ | Style fixes, updated outdated documentation, cleaned import patterns, removed extraneous emojis |

*Note: The CORS fix restricts the allowed origins for the WebUI to safe values (e.g., localhost/ingress) and prevents unintended cross-origin requests.

## [0.4.0-beta] - 2026-02-10

### Added

- **WebUI**: Terminal-style web dashboard accessible via Home Assistant ingress (sidebar panel).
  - **Dashboard**: Real-time server status with latency indicators, attached device count, quick-action buttons.
  - **Devices**: View attached devices, attach/detach individual or all devices, bulk operations with checkboxes.
  - **Discovery**: Discover remote USB devices from any server, network subnet scanner to find USB/IP servers.
  - **Live Logs**: WebSocket-powered real-time log viewer with level filtering, pause/resume, and copy-to-clipboard.
  - **Events Timeline**: Persistent event log tracking all attach/detach/discover/config operations.
  - **Config Editor**: Edit all configuration options (log level, server, delay, devices) directly from the UI.
  - **Backup & Restore**: Export/import configuration as JSON files.
- **Network Server Scanner**: Scan a subnet for USB/IP servers (port 3240 probe).
- **Connection Health Monitor**: Background health checks every 30s with latency display.
- **USB Device Database Lookup**: Resolve vendor:product IDs to human-readable names using installed `hwids-usb`.
- **HA Notifications**: Push persistent notifications to Home Assistant on device attach/detach events.
- **Terminal Themes**: 5 color schemes (Green, Amber, Blue, Dracula, Matrix) with CRT scanline effect.
- **Bulk Operations**: Attach-all / Detach-all buttons with selective multi-device operations.
- **Event Logging**: JSONL-based event log at `/tmp/usbip_events.jsonl` written by init, service, and cleanup scripts.
- **Python shared library** (`usbip_lib`): Reusable package for USB/IP operations, config, events, and logging.
- **Test suite**: 114 pytest tests (unit + integration) with 92% library coverage.

### Changed

- **All shell scripts replaced with Python**: `load_modules`, `init_devices`, `detach_devices`, and all s6 `run`/`finish` scripts.
  - Shared logic extracted to `rootfs/usr/local/lib/usbip_lib/` (constants, logging, events, config, usbip modules).
  - Generated bash `mount_devices` script replaced by JSON device manifest (`/tmp/device_manifest.json`).
  - WebUI (`app.py`) refactored to use the shared library, removing ~150 lines of duplicated helpers.
- Version bump to 0.4.0-beta.
- Dockerfile now installs Python 3, Flask, Flask-SocketIO, and gevent for the WebUI backend.
- Added s6 service `webui` for the Flask web server (runs alongside existing `usbip` service).
- Config schema now includes `ingress: true`, `ingress_port: 8099`, `panel_icon: mdi:console`.

## [0.3.0-beta] - 2026-02-10

### Fixed

- **Issue #11**: Multiple devices from the same server failing to attach due to race condition. Added configurable delay (`attach_delay`, default 2s) and retry logic (3 attempts per device) between consecutive attach operations.
- **Issue #10**: Restored per-device server address support. Each device can now specify an optional `server` field to override the global `usbipd_server_address`, enabling attachment from multiple USB/IP servers simultaneously.
- **Issue #9**: Unreliable device detachment on app stop. Rewrote detach logic to always query actual kernel state via `usbip port` instead of relying on fragile temp file / index-based port matching. Added blind detach fallback if port query fails.

### Added

- `attach_delay` configuration option (0-30 seconds, default: 2) to control delay between device attachment attempts.
- Optional `server` field per device entry to allow attaching devices from different USB/IP servers.
- Retry logic in mount script: each device attachment is attempted up to 3 times before giving up.
- Partial success handling: if some devices attach but others fail, the service starts with a warning instead of failing entirely.
- Delay between detach operations (0.5s) to avoid server-side race conditions.
- Blind detach fallback (ports 0-15) when `usbip port` command fails during cleanup.

### Changed

- Mount script is now generated with a proper `attach_device()` function including retry logic and per-device error handling.
- Device discovery now runs against all unique server addresses (global + per-device).
- Device details file format now includes server IP for accurate cross-server device lookup.
- Run script now checks actual attachment status via `usbip port` after mount, instead of parsing the mount script.

## [0.2.0-beta] - 2025-10-28

### Changed

- Configuration format: `bus_id` → `device_id` for improved user experience and more reliable device identification.
- Automatic bus ID resolution from device IDs via discovery for better portability across different USB port topologies.
- Enhanced device detachment logging to include device descriptions (Bus ID and Server IP) instead of just port numbers for better troubleshooting.
- Improved detach script error handling and made it executable.

### Added

- Support for both `device_id` (Vendor:Product ID format like `0658:0200`) and `bus_id` (Port format like `1-1.2`) in a single `device_or_bus_id` field. The script automatically detects the format and handles it appropriately.
- `name` field for each device to provide descriptive labels for better readability and management in logs and UI.

### Breaking Changes

- **UPGRADE NOTE**: When upgrading from v0.1.x or earlier, you must completely reinstall the app (uninstall, activate "Also permanently delete this app's data" → install) for the new configuration format to take effect. Turn off protection mode. [Read more here about it](#security-considerations)

## [0.1.3] - 2024-12-21

### Changed

- Added an automation example to the README.md.

## [0.1.2] - 2024-10-18

### Added

- `log_level` option to configure the verbosity of the app logs.
- Enhanced scripts to respect the `log_level` setting for better debugging.

## [0.1.1] - 2024-10-09

### Added

- `repository.yaml` file for Home Assistant app repository metadata, enabling app discovery and compatibility with Home Assistant.

## [0.1.0] - 2024-10-07

### Added

- Initial release.

---

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
