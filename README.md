# USBIP Client Home Assistant Add-on

This is a Home Assistant add-on that acts as a USBIP client. It connects to an existing USBIP server to access remote USB devices, making them available to Home Assistant.

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

- **server_address**: The IP address of the USBIP server.
- **bus_id**: The bus ID of the USB device on the USBIP server.

Example configuration:

```yaml
server_addresses:
  - "192.168.1.44"
  - "192.168.1.44"
bus_ids:
  - "1-1.1.3"
  - "1-1.2"
```

Replace `192.168.1.44` with your USBIP server IP address and provide the correct bus ID of the USB device.

## Usage

- Once the add-on is configured and started, it will connect to the specified USBIP server and attach to the USB device.
- The device will then be available for use in Home Assistant integrations.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
