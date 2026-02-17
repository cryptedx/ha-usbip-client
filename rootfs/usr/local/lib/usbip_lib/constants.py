"""Shared constants for the USB/IP client app."""

import os

# Temp / state files
EVENTS_FILE = "/tmp/usbip_events.jsonl"
DEVICE_DETAILS_FILE = "/tmp/device_details.txt"
ATTACHED_DEVICES_FILE = "/tmp/attached_devices.txt"
DEVICE_MANIFEST_FILE = "/tmp/device_manifest.json"

# Persistent files (/data survives addon restarts)
LATENCY_HISTORY_FILE = "/data/usbip_latency_history.jsonl"

# Latency history tuning
LATENCY_HISTORY_WINDOW_SECONDS = 3600
LATENCY_FLUSH_INTERVAL_SECONDS = 300
LATENCY_HEARTBEAT_SECONDS = 900
LATENCY_CHANGE_ABS_THRESHOLD_MS = 10.0
LATENCY_CHANGE_REL_THRESHOLD = 0.2

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
