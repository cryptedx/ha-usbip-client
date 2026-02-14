#!/command/with-contenv python3
"""s6 cont-init script: Load the vhci-hcd kernel module."""

import sys

from usbip_lib.config import get_app_config
from usbip_lib.logging_setup import setup_logging
from usbip_lib.usbip import load_kernel_module

config = get_app_config()
log_level = config.get("log_level", "info")
logger = setup_logging(log_level, name="load_modules")

if not load_kernel_module("vhci-hcd"):
    sys.exit(1)
