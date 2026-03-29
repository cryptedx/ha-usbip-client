# USB/IP Client Home Assistant App

![Supports aarch64 Architecture][aarch64-shield]
![Supports amd64 Architecture][amd64-shield]
![Project Maintenance][maintenance-shield]

This is a Home Assistant app that acts as a USB/IP client. It connects to an existing USB/IP server to access remote USB devices, making them available to Home Assistant.

## Background story

Huge thanks to [irakhlin's hassio-usbip-mounter](https://github.com/irakhlin/hassio-usbip-mounter) for the inspiration! While trying out his app, I encountered some strange behavior with my HA apps, so I had to remove it, leaving me with an unresolved challenge — how to achieve high availability on my Proxmox cluster. So, I decided to create my own USB/IP app, and here it is.

Special thanks to [rogerfar](https://github.com/rogerfar) and [Rene-Sackers](https://github.com/Rene-Sackers) for [their great ideas and discussions](https://github.com/cryptedx/ha-usbip-client/pull/8), which made it possible to mount devices via device ID in addition to bus ID.

## Contributing

For development, contribution, architecture details, and release automation see [DEVELOPER.md](DEVELOPER.md).
For apppublishing workflow see [docs/publishing.md](docs/publishing.md).

## Features

- Connects to a remote USB/IP server.
- Exposes remote USB devices for use in Home Assistant.
- Configurable log levels for easier debugging.
- **USB Device Monitoring**: Automatically detects lost USB devices and attempts reattachment with configurable retries and cooldowns.
- **Auto-Reattach**: Failed devices are reattached automatically after disconnection, with notifications sent to Home Assistant.
- **Dependent App Health Monitoring**: Monitors the health of dependent apps (e.g., Zigbee2MQTT, Z-Wave JS) and restarts them if they enter error state.
- **WebUI Dashboard**: Terminal-style web interface for device management, live logs, event timeline, and configuration editing.
- **Network Server Discovery**: Scan subnet for available USB/IP servers.
- **Bulk Operations**: Attach/detach all devices at once.
- **Real-time Notifications**: Push notifications to Home Assistant on device events.

## Installation

1. Add it to your Home Assistant app store as a custom repository.

    [![Open your Home Assistant instance and show the app repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https://github.com/cryptedx/ha-usbip-client)

2. Install the **USB/IP Client** app.
3. Configure the app options to specify the USB/IP server IP address, USB device bus IDs, and desired log level.
4. Start the app.

## Distribution and publishing

- This repository is published as a **Home Assistant App repository**.
- HACS is not used for publishing this app type.
- If a HACS package is needed in the future, it must be delivered as a separate HACS-compatible repository (for example, integration/card/theme), not as this app.

### Development branch install

⚠️ The development branch contains latest features and fixes, but may be unstable.

1. Add repository URL with dev branch: `https://github.com/cryptedx/ha-usbip-client.git#dev`
2. Follow the same installation steps.
3. Reinstall the app when switching between stable and development versions if needed.

## Configuration

- **log_level**: Optional log verbosity. Default `info`. Allowed: `trace`, `debug`, `info`, `notice`, `warning`, `error`, `fatal`.
- **usbipd_server_address**: IP address of the USB/IP server.
- **attach_delay**: Optional delay between attachment attempts. Default `2`, range `0-30`.
- **monitor_interval**: Optional health check interval. Default `30`, range `10-300`.
- **reattach_retries**: Optional reattach retries. Default `3`, range `0-10`.
- **restart_retries**: Optional dependent app restart retries. Default `3`, range `0-10`.
- **dependent_apps**: Optional list with `name` and `slug`.
- **Recommended for dependent apps**: Let USB/IP Client manage dependent apps and disable **Start on boot** and **Watchdog** for each of them in Home Assistant.
- **devices**: Device list containing:
  - **name**: Display name.
  - **device_or_bus_id**: Bus ID (`1-1.1.3`) or USB device ID (`0658:0200`).

Example:

```yaml
log_level: info
usbipd_server_address: "192.168.1.44"
attach_delay: 2
monitor_interval: 30
reattach_retries: 3
restart_retries: 3
dependent_apps:
  - name: "Zigbee2MQTT"
    slug: "45df7312_zigbee2mqtt"
  - name: "Z-Wave JS"
    slug: "core_zwave_js"
devices:
  - name: "Zigbee Stick"
    device_or_bus_id: "1-1.1.3"
  - name: "Z-Wave Stick"
    device_or_bus_id: "1-1.2"
```

## Usage

- After startup, the app connects to the configured USB/IP server and attaches configured devices.
- Attached devices become available in Home Assistant integrations.
- Use the WebUI panel for discovery, attach/detach actions, logs, and event tracking.

## Screenshots

- **Dashboard**
  ![Dashboard][screenshot-dashboard]
- **Devices list**
  ![Devices][screenshot-devices]
- **Server discovery**
  ![Discovery][screenshot-discovery]
- **Live logs**
  ![Logs][screenshot-logs]
- **Event timeline**
  ![Events][screenshot-events]
- **Configuration editor**
  ![Config][screenshot-config]

## Security Considerations

The app performs kernel- and USB-level operations and therefore still requires elevated privileges on the host. Important changes and current facts:

- Protection Mode: **you do not need to disable Protection Mode** for the app to run — the app works with Protection Mode enabled.
- AppArmor: enabled by default with an addon-specific profile aligned to the actual runtime scripts and binaries.
- Required capabilities: the app requests only the kernel/network capabilities needed for USB/IP (`NET_ADMIN`, `SYS_ADMIN`, `SYS_MODULE`, `SYS_RAWIO`) and `vhci-hcd` kernel module access.
- Device access: raw USB and `/dev/vhci` are mapped explicitly instead of using Docker-style full privileged access.
- Network & host access: the app uses the host network stack for USB/IP communication.
- Diagnostics: the Dashboard includes first-run checks (module loaded, usbip command available, server reachable) to speed up troubleshooting.

Recommendations

- Use the app in a trusted network environment and keep Home Assistant updated.
- Review the `privileged` and `host_network` settings in `config.yaml` before deploying to sensitive hosts.
- For development or advanced deployment details see `DEVELOPER.md`.

## License

This project is licensed under the MIT License.

[aarch64-shield]: https://img.shields.io/badge/aarch64-yes-green.svg
[amd64-shield]: https://img.shields.io/badge/amd64-yes-green.svg
[maintenance-shield]: https://img.shields.io/maintenance/yes/2026.svg

[screenshot-dashboard]: https://raw.githubusercontent.com/cryptedx/ha-usbip-client/dev/docs/images/10-dashboard.png
[screenshot-devices]: https://raw.githubusercontent.com/cryptedx/ha-usbip-client/dev/docs/images/20-devices.png
[screenshot-discovery]: https://raw.githubusercontent.com/cryptedx/ha-usbip-client/dev/docs/images/30-discovery.png
[screenshot-logs]: https://raw.githubusercontent.com/cryptedx/ha-usbip-client/dev/docs/images/40-logs.png
[screenshot-events]: https://raw.githubusercontent.com/cryptedx/ha-usbip-client/dev/docs/images/50-events.png
[screenshot-config]: https://raw.githubusercontent.com/cryptedx/ha-usbip-client/dev/docs/images/60-config.png
