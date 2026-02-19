#!/command/with-contenv python3
"""s6 cont-init script: Discover devices and build the device manifest.

Replaces create_devices.sh — reads app config, discovers available devices
from all configured servers, resolves device IDs to bus IDs, and writes a
JSON manifest for the usbip service to consume.
"""

import sys

from usbip_lib.config import get_app_config
from usbip_lib.config import get_unique_servers
from usbip_lib.events import write_event
from usbip_lib.logging_setup import setup_logging
from usbip_lib.usbip import (
    build_device_manifest,
    discover_devices,
    write_device_manifest,
)


def main() -> int:
    config = get_app_config()
    log_level = config.get("log_level", "info")
    logger = setup_logging(log_level, name="init_devices")

    logger.info("")
    logger.info(
        "-----------------------------------------------------------------------"
    )
    logger.info("-------------------- Starting USB/IP Client App --------------------")
    logger.info(
        "-----------------------------------------------------------------------"
    )
    logger.info("")

    default_server = config.get("usbipd_server_address", "")
    attach_delay = config.get("attach_delay", 2)

    if not default_server:
        logger.error("No usbipd_server_address configured.")
        return 1

    logger.info("Attach delay between devices: %ds", attach_delay)

    # Collect unique server addresses
    servers = get_unique_servers(config)

    logger.debug("Unique servers to discover: %s", ", ".join(servers))

    # Discover available devices from all servers
    discovery_data = discover_devices(list(servers))

    # Build device manifest
    manifest = build_device_manifest(config, discovery_data)
    write_device_manifest(manifest)

    logger.info(
        "Device configuration complete. Ready to attach %d device(s).", len(manifest)
    )

    # Write discovery event for WebUI
    write_event(
        "discover",
        f"Discovered {len(discovery_data)} device(s) during init",
        server=default_server,
    )

    return 0


sys.exit(main())
