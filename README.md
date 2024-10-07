# USBIP Client Home Assistant Add-on

This is a Home Assistant add-on that acts as a USBIP client. It connects to an existing USBIP server to access remote USB devices, making them available to Home Assistant.

## Background story

Huge thanks to [irakhlin's hassio-usbip-mounter](https://github.com/irakhlin/hassio-usbip-mounter) for the inspiration! While trying out his addon, I encountered some strange behavior with my HA addons, so I had to remove it, leaving me with an unresolved challenge — how to achieve high availability on my Proxmox cluster. So, I decided to create my own USBIP addon, and here it is.

## Features

- Connects to a remote USBIP server.
- Exposes remote USB devices for use in Home Assistant.

## Installation

1. Clone this repository or add it to your Home Assistant add-on store as a custom repository.
2. Install the **USBIP Client** add-on.
3. Configure the add-on options to specify the USBIP server IP address and the USB device bus ID.
4. Start the add-on.

## Configuration

The add-on requires a list of devices with the following options:

- **discovery_server_address**: The IP address of the USBIP server used for discovery.
- **server_address**: The IP address of the USBIP server.
- **bus_id**: The bus ID of the USB device on the USBIP server. Example: `1-1.1.3` or `1-1.2`.

Example configuration:

```yaml
discovery_server_address: "192.168.1.44"
devices:
  - server_address: "192.168.1.44"
    bus_id: "1-1.1.3"
  - server_address: "192.168.1.44"
    bus_id: "1-1.2"
```

Replace `192.168.1.44` with your USBIP server IP address and provide the correct bus ID of the USB device.

## Usage

- Once the add-on is configured and started, it will connect to the specified USBIP server and attach to the USB device.
- The device will then be available for use in Home Assistant integrations.

## Security Considerations

This add-on requires elevated privileges to access and manage USB devices, which has potential security implications:

- **Full Access**: The add-on is granted full access to the host system, which allows it to interact directly with USB devices and kernel modules.
- **Kernel Modules**: The add-on loads the vhci-hcd kernel module to enable USBIP functionality. Loading kernel modules can potentially introduce vulnerabilities if not properly managed.
- **Host Network**: The add-on uses the host's network stack (host_network: true). This means that any vulnerabilities in the USBIP protocol could potentially impact the host system.
- **Privileged Operations**: The add-on requires several Linux capabilities (NET_ADMIN, SYS_ADMIN, SYS_RAWIO, etc.) to perform USB management operations. These permissions are powerful and, if exploited, could compromise the host system.

It is recommended to:

- Only use this add-on in a trusted network environment.
- Regularly update the add-on to incorporate security patches.
- Limit access to the Home Assistant instance to reduce exposure.

## TODO List

- **Automatic Device Discovery**: Implement functionality to discover and list available USB devices from the USBIP server. *(Done)*
- **Hot-Plugging Support**: Add support for dynamically attaching and detaching devices without requiring a restart of the add-on.
- **Error Handling Improvements**: Enhance error handling to provide more detailed feedback when operations fail.
- **Device Filtering**: Allow users to specify filtering rules to automatically attach only specific types of USB devices.
- **Encryption Support**: Add support for encrypting USBIP communication to enhance security, especially in less trusted network environments.
- **Web Interface**: Develop a simple web interface for managing USB devices and configurations directly from Home Assistant.
- **Device Status Monitoring**: Add monitoring features to track the status of attached devices and provide alerts if a device becomes unavailable.

## Accessing the USBIP Container in Home Assistant via SSH

1. **SSH into your Home Assistant instance.**

2. **Locate the USBIP container:**

    Run the following command to find the USBIP container ID:

    ```bash
    docker ps | grep usbip
    ```

3. **Access the container's bash shell**

    Once you have the <container_id>, use it in this command to enter the container:

    ```bash
    docker exec -it <container_id> /bin/bash
    ```

## License

This project is licensed under the MIT License.
