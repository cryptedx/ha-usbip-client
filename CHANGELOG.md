# Changelog

## [0.3.0-beta] - 2026-02-10

### Fixed

- **Issue #11**: Multiple devices from the same server failing to attach due to race condition. Added configurable delay (`attach_delay`, default 2s) and retry logic (3 attempts per device) between consecutive attach operations.
- **Issue #10**: Restored per-device server address support. Each device can now specify an optional `server` field to override the global `usbipd_server_address`, enabling attachment from multiple USB/IP servers simultaneously.
- **Issue #9**: Unreliable device detachment on add-on stop. Rewrote detach logic to always query actual kernel state via `usbip port` instead of relying on fragile temp file / index-based port matching. Added blind detach fallback if port query fails.

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

- **UPGRADE NOTE**: When upgrading from v0.1.x or earlier, you must completely reinstall the add-on (uninstall, activate "Also permanently delete this add-on's data" → install) for the new configuration format to take effect. Turn off protection mode. [Read more here about it](#security-considerations)

## [0.1.3] - 2024-12-21

### Changed

- Added an automation example to the README.md.

## [0.1.2] - 2024-10-18

### Added

- `log_level` option to configure the verbosity of the add-on logs.
- Enhanced scripts to respect the `log_level` setting for better debugging.

## [0.1.1] - 2024-10-09

### Added

- `repository.yaml` file for Home Assistant add-on repository metadata, enabling add-on discovery and compatibility with Home Assistant.

## [0.1.0] - 2024-10-07

### Added

- Initial release.

---

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
