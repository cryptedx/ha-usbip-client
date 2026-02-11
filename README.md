# USB/IP Client Home Assistant App

![Supports aarch64 Architecture][aarch64-shield]
![Supports amd64 Architecture][amd64-shield]
![Supports armhf Architecture][armhf-shield]
![Supports armv7 Architecture][armv7-shield]
![Supports i386 Architecture][i386-shield]

![Project Maintenance][maintenance-shield]

This is a Home Assistant app (formerly called add-on) that acts as a USB/IP client. It connects to an existing USB/IP server to access remote USB devices, making them available to Home Assistant.

## Background story

Huge thanks to [irakhlin's hassio-usbip-mounter](https://github.com/irakhlin/hassio-usbip-mounter) for the inspiration! While trying out his app, I encountered some strange behavior with my HA apps, so I had to remove it, leaving me with an unresolved challenge — how to achieve high availability on my Proxmox cluster. So, I decided to create my own USB/IP app, and here it is.

Special thanks to [rogerfar](https://github.com/rogerfar) and [Rene-Sackers](https://github.com/Rene-Sackers) for [their great ideas and discussions](https://github.com/cryptedx/ha-usbip-client/pull/8), which made it possible to mount devices via device ID in addition to bus ID.

## Features

- Connects to a remote USB/IP server.
- Exposes remote USB devices for use in Home Assistant.
- Configurable log levels for easier debugging.
- **USB Device Monitoring**: Automatically detects lost USB devices and attempts reattachment with configurable retries and cooldowns.
- **Auto-Reattach**: Failed devices are reattached automatically after disconnection, with notifications sent to Home Assistant.
- **Dependent Add-on Health Monitoring**: Monitors the health of dependent add-ons (e.g., Zigbee2MQTT, Z-Wave JS) and restarts them if they enter error state.
- **WebUI Dashboard**: Terminal-style web interface for device management, live logs, event timeline, and configuration editing.
- **Network Server Discovery**: Scan subnet for available USB/IP servers.
- **Bulk Operations**: Attach/detach all devices at once.
- **Real-time Notifications**: Push notifications to Home Assistant on device events.

## Todo

- [X] create webui where logs can be inspected live and devices, discovered/polled, attached, detached via a dropdown
- [X] How to check if other containers which rely on this are still healthy? 45df7312-zigbee2mqtt and core-zwave-js
- [X] Notify user if usb device has failed, etc.
- [X] Change all shell scripts to Python for better error handling and maintainability

## Installation

1. Add it to your Home Assistant app store as a custom repository.

    [![Open your Home Assistant instance and show the add app repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https://github.com/cryptedx/ha-usbip-client)

2. Install the **USB/IP Client** app.
3. Configure the app options to specify the USB/IP server IP address, USB device bus IDs, and desired log level.
4. Turn off protection mode. [Read more here about it](#security-considerations)
5. Start the app.

## Development Branch

⚠️ **Warning**: The development branch contains the latest features and bug fixes but may be unstable. Use at your own risk.

To install the development version of the **USB/IP Client** app:

1. Add the repository URL with the dev branch: `https://github.com/cryptedx/ha-usbip-client.git#dev`
2. Follow the same installation steps as above.
3. Note that you may need to reinstall the app when switching between stable and development versions.

The app requires the following configuration options:

- **log_level**: (Optional) Sets the verbosity of the app logs. Default is `info`. Available options are `trace`, `debug`, `info`, `notice`, `warning`, `error`, `fatal`.
- **usbipd_server_address**: The IP address of the USB/IP server.
- **attach_delay**: (Optional) Delay in seconds between device attachment attempts. Default is `2`. Range: 0-30.
- **monitor_interval**: (Optional) Interval in seconds for device health monitoring. Default is `30`. Range: 10-300.
- **reattach_retries**: (Optional) Number of retries for device reattachment. Default is `3`. Range: 0-10.
- **restart_retries**: (Optional) Number of retries for add-on restart. Default is `3`. Range: 0-10.
- **dependent_addons**: (Optional) List of dependent add-ons to monitor and restart if they fail. Each entry has `name` and `slug`.
- **devices**: A list of devices with the following options:
  - **name**: The name of the USB device.
  - **device_or_bus_id**: The bus ID or device ID of the USB device on the USB/IP server. Example: `1-1.1.3` or `0658:0200`.

Example configuration:

```yaml
log_level: info
usbipd_server_address: "192.168.1.44"
attach_delay: 2
monitor_interval: 30
reattach_retries: 3
restart_retries: 3
dependent_addons:
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

Replace `192.168.1.44` with your USB/IP server IP address and provide the correct bus IDs or device IDs of the USB devices.

## Usage

- Once the app is configured and started, it will connect to the specified USB/IP server and attach to the USB devices.
- The devices will then be available for use in Home Assistant integrations.
- Adjust the `log_level` in the configuration to control the verbosity of the logs for troubleshooting.

## Security Considerations

This app requires elevated privileges to access and manage USB devices, which has potential security implications:

- **Full Access**: The app is granted full access to the host system, which allows it to interact directly with USB devices and kernel modules.
- **Kernel Modules**: The app loads the vhci-hcd kernel module to enable USB/IP functionality. Loading kernel modules can potentially introduce vulnerabilities if not properly managed.
- **Host Network**: The app uses the host's network stack (host_network: true). This means that any vulnerabilities in the USB/IP protocol could potentially impact the host system.
- **Privileged Operations**: The app requires several Linux capabilities (NET_ADMIN, SYS_ADMIN, SYS_RAWIO, etc.) to perform USB management operations. These permissions are powerful and, if exploited, could compromise the host system.

It is recommended to:

- Only use this app in a trusted network environment.
- Regularly update the app to incorporate security patches.
- Limit access to the Home Assistant instance to reduce exposure.

## Related Automation for App Management

To automate the management of other Home Assistant apps based on the status of this USB/IP Client app, you can use the following automation.

*Note: The feedback of the app status is very sluggish at the time I created this automation. This means that if you stop the USB/IP Client Home Assistant app, for example, it takes 1-5 minutes for the status of the sensor to be updated!*

**Access App Entities:**

1. Navigate to Settings > Devices & Services.
2. Locate and select Home Assistant Supervisor from the device list.
3. Click on Entities to view all entities associated with the Supervisor.

**Enable the Running State Sensor:**

1. In the entities list, find the binary sensor corresponding to the app you wish to monitor. These sensors are typically named in the format binary_sensor.[app_name]_running.
2. Click on the desired sensor to open its details.
3. Click on the Settings (cog) icon in the top-right corner.
4. Toggle the Enabled switch to activate the sensor.
5. Click Update to save your changes.

```yaml
alias: USB/IP Client Home Assistant App Management
description: >-
  Starts or stops apps when the USB/IP client is on/off, with an optional
  startup delay.
triggers:
  - entity_id:
      - binary_sensor.ha_usbip_client_running
    to: "on"
    id: usbip_start
    trigger: state
  - entity_id:
      - binary_sensor.ha_usbip_client_running
    to: "off"
    id: usbip_stop
    trigger: state
actions:
  - choose:
      - conditions:
          - condition: template
            value_template: "{{ trigger.id == 'usbip_start' }}"
        sequence:
          - delay:
              seconds: "{{ start_delay }}"
          - repeat:
              for_each: "{{ managed_apps }}"
              sequence:
                - if:
                    - condition: template
                      value_template: "{{ is_state(repeat.item.app_sensor, 'off') }}"
                  then:
                    - data:
                        addon: "{{ repeat.item.app_slug }}"
                      action: hassio.addon_start
      - conditions:
          - condition: template
            value_template: "{{ trigger.id == 'usbip_stop' }}"
        sequence:
          - repeat:
              for_each: "{{ managed_apps }}"
              sequence:
                - if:
                    - condition: template
                      value_template: "{{ is_state(repeat.item.app_sensor, 'on') }}"
                  then:
                    - data:
                        addon: "{{ repeat.item.app_slug }}"
                      action: hassio.addon_stop
mode: single
variables:
  start_delay: 0
  managed_apps:
    - app_name: Zigbee2MQTT
      app_sensor: binary_sensor.zigbee2mqtt_running
      app_slug: 45df7312_zigbee2mqtt
    - app_name: Z-Wave JS
      app_sensor: binary_sensor.zwave_js_running
      app_slug: core_zwave_js

```

## Accessing the USB/IP Container in Home Assistant via SSH

1. **SSH into your Home Assistant instance.**

2. **Locate the USB/IP container:**

    Run the following command to find the USB/IP container ID:

    ```bash
    docker ps | grep usbip
    ```

3. **Access the container's bash shell**

    Once you have the `<container_id>`, use it in this command to enter the container:

    ```bash
    docker exec -it <container_id> /bin/bash
    ```

## License

This project is licensed under the MIT License.

[aarch64-shield]: https://img.shields.io/badge/aarch64-yes-green.svg
[amd64-shield]: https://img.shields.io/badge/amd64-yes-green.svg
[armhf-shield]: https://img.shields.io/badge/armhf-yes-green.svg
[armv7-shield]: https://img.shields.io/badge/armv7-yes-green.svg
[i386-shield]: https://img.shields.io/badge/i386-yes-green.svg
[maintenance-shield]: https://img.shields.io/maintenance/yes/2026.svg
