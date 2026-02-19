#!/command/with-contenv python3
"""s6 cont-finish script: Detach all USB/IP devices on container shutdown."""

import sys

from usbip_lib.events import write_event
from usbip_lib.logging_setup import setup_logging
from usbip_lib.usbip import cleanup_temp_files, detach_all, run_cmd

logger = setup_logging("info", name="detach_devices")

logger.info("\U0001f534 Container stopping - detaching USB/IP devices")

# Check if usbip is available
rc, _, _ = run_cmd(["which", "usbip"])
if rc != 0:
    logger.warning("usbip command not found, cannot detach devices")
    sys.exit(0)

detached, failed = detach_all()

# Write event for WebUI
write_event(
    "detach_all",
    f"Container stop: {detached} detached, {failed} failed",
)

# Clean up temp files
cleanup_temp_files()

logger.info("USB/IP device cleanup finished")
logger.info("\U0001f534 Container stopped")
