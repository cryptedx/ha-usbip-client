"""Shared constants for the USB/IP client app."""

import os

# Temp / state files
EVENTS_FILE = "/tmp/usbip_events.jsonl"
DEVICE_DETAILS_FILE = "/tmp/device_details.txt"
ATTACHED_DEVICES_FILE = "/tmp/attached_devices.txt"
DEVICE_MANIFEST_FILE = "/tmp/device_manifest.json"

# System paths
USB_IDS_FILE = "/usr/share/hwdata/usb.ids"

# Home Assistant Supervisor
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
SUPERVISOR_URL = os.environ.get("SUPERVISOR_URL", "http://supervisor")

# USB/IP defaults
DEFAULT_ATTACH_DELAY = 2
DEFAULT_ATTACH_RETRIES = 3
USBIP_PORT = 3240
BLIND_DETACH_MAX_PORT = 15
