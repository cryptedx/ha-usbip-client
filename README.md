# USB/IP Client Home Assistant Add-on

![Supports aarch64 Architecture][aarch64-shield]
![Supports amd64 Architecture][amd64-shield]
![Supports armhf Architecture][armhf-shield]
![Supports armv7 Architecture][armv7-shield]
![Supports i386 Architecture][i386-shield]

![Project Maintenance][maintenance-shield]

This is a Home Assistant add-on that acts as a USB/IP client. It connects to an existing USB/IP server to access remote USB devices, making them available to Home Assistant.

## Background story

Huge thanks to [irakhlin's hassio-usbip-mounter](https://github.com/irakhlin/hassio-usbip-mounter) for the inspiration! While trying out his addon, I encountered some strange behavior with my HA addons, so I had to remove it, leaving me with an unresolved challenge — how to achieve high availability on my Proxmox cluster. So, I decided to create my own USB/IP addon, and here it is.

## Features

- Connects to a remote USB/IP server.
- Exposes remote USB devices for use in Home Assistant.
- Configurable log levels for easier debugging.

## Installation

1. Add it to your Home Assistant add-on store as a custom repository.

    [![Open your Home Assistant instance and show the add add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https://github.com/cryptedx/ha-usbip-client)

2. Install the **USB/IP Client** add-on.
3. Configure the add-on options to specify the USB/IP server IP address, USB device bus IDs, and desired log level.
4. Turn off protection mode. [Read more here about it](#security-considerations)
5. Start the add-on.

## Configuration

The add-on requires the following configuration options:

- **log_level**: (Optional) Sets the verbosity of the add-on logs. Default is `info`. Available options are `trace`, `debug`, `info`, `notice`, `warning`, `error`, `fatal`.
- **discovery_server_address**: The IP address of the USB/IP server used for device discovery.
- **devices**: A list of devices with the following options:
  - **server_address**: The IP address of the USB/IP server.
  - **bus_id**: The bus ID of the USB device on the USB/IP server. Example: `1-1.1.3` or `1-1.2`.

Example configuration:

```yaml
log_level: info
discovery_server_address: "192.168.1.44"
devices:
  - server_address: "192.168.1.44"
    bus_id: "1-1.1.3"
  - server_address: "192.168.1.44"
    bus_id: "1-1.2"
```

Replace `192.168.1.44` with your USB/IP server IP address and provide the correct bus IDs of the USB devices.

## Usage

- Once the add-on is configured and started, it will connect to the specified USB/IP server and attach to the USB devices.
- The devices will then be available for use in Home Assistant integrations.
- Adjust the `log_level` in the configuration to control the verbosity of the logs for troubleshooting.

## Security Considerations

This add-on requires elevated privileges to access and manage USB devices, which has potential security implications:

- **Full Access**: The add-on is granted full access to the host system, which allows it to interact directly with USB devices and kernel modules.
- **Kernel Modules**: The add-on loads the vhci-hcd kernel module to enable USB/IP functionality. Loading kernel modules can potentially introduce vulnerabilities if not properly managed.
- **Host Network**: The add-on uses the host's network stack (host_network: true). This means that any vulnerabilities in the USB/IP protocol could potentially impact the host system.
- **Privileged Operations**: The add-on requires several Linux capabilities (NET_ADMIN, SYS_ADMIN, SYS_RAWIO, etc.) to perform USB management operations. These permissions are powerful and, if exploited, could compromise the host system.

It is recommended to:

- Only use this add-on in a trusted network environment.
- Regularly update the add-on to incorporate security patches.
- Limit access to the Home Assistant instance to reduce exposure.

## Related Automation for Add-on Management

To automate the management of other Home Assistant add-ons based on the status of this USB/IP Client add-on, you can use the following automation.

*Note: The feedback of the addon status is very sluggish at the time I created this automation. This means that if you stop the USB/IP Client Home Assistant add-on, for example, it takes 1-5 minutes for the status of the sensor to be updated!*

```yaml
alias: USB/IP Client Home Assistant Add-on Management
description: >-
  Starts or stops add-ons when the USB/IP client is on/off, with an optional
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
              for_each: "{{ managed_addons }}"
              sequence:
                - if:
                    - condition: template
                      value_template: "{{ is_state(repeat.item.addon_sensor, 'off') }}"
                  then:
                    - data:
                        addon: "{{ repeat.item.addon_slug }}"
                      action: hassio.addon_start
      - conditions:
          - condition: template
            value_template: "{{ trigger.id == 'usbip_stop' }}"
        sequence:
          - repeat:
              for_each: "{{ managed_addons }}"
              sequence:
                - if:
                    - condition: template
                      value_template: "{{ is_state(repeat.item.addon_sensor, 'on') }}"
                  then:
                    - data:
                        addon: "{{ repeat.item.addon_slug }}"
                      action: hassio.addon_stop
mode: single
variables:
  start_delay: 0
  managed_addons:
    - addon_name: Zigbee2MQTT
      addon_sensor: binary_sensor.zigbee2mqtt_running
      addon_slug: 45df7312_zigbee2mqtt
    - addon_name: Z-Wave JS
      addon_sensor: binary_sensor.zwave_js_running
      addon_slug: core_zwave_js

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
[maintenance-shield]: https://img.shields.io/maintenance/yes/2024.svg
