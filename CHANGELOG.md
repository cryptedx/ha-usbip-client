# Changelog

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
