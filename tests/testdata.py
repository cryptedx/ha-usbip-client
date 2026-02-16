"""Shared test data constants used across unit and integration tests."""

# ---------------------------------------------------------------------------
# Sample command outputs
# ---------------------------------------------------------------------------

SAMPLE_USBIP_PORT_OUTPUT = """\
Imported USB devices
====================
Port 00: <Port in Use> at High Speed(480Mbps)
       unknown vendor : unknown product (0658:0200)
       1-1 -> usbip://192.168.1.44:3240/1-1.4
           -> remote bus/dev 001/005
Port 01: <Port in Use> at Full Speed(12Mbps)
       unknown vendor : unknown product (10c4:ea60)
       2-1 -> usbip://192.168.1.44:3240/1-1.3
           -> remote bus/dev 001/004
"""

SAMPLE_USBIP_PORT_EMPTY = """\
Imported USB devices
====================
"""

SAMPLE_USBIP_PORT_SINGLE = """\
Imported USB devices
====================
Port 00: <Port in Use> at High Speed(480Mbps)
       unknown vendor : unknown product (0658:0200)
       1-1 -> usbip://192.168.1.44:3240/1-1.4
           -> remote bus/dev 001/005
"""

SAMPLE_USBIP_LIST_OUTPUT = """\
Exportable USB devices
======================
 - 192.168.1.44
      1-1.3: Silicon Labs : CP210x UART Bridge (10c4:ea60)
           : USB\\VID_10C4&PID_EA60\\0001
           : (Defined at Interface level) (00/00/00)
      1-1.4: Sigma Designs, Inc. : Aeotec Z-Stick Gen5 (0658:0200)
           : USB\\VID_0658&PID_0200\\12345678
           : (Defined at Interface level) (02/02/01)
"""

SAMPLE_USBIP_LIST_EMPTY = """\
Exportable USB devices
======================
 - 192.168.1.44
"""

SAMPLE_APP_CONFIG = {
    "log_level": "info",
    "usbipd_server_address": "192.168.1.44",
    "attach_delay": 2,
    "monitor_interval": 30,
    "reattach_retries": 3,
    "restart_retries": 3,
    "notifications_enabled": True,
    "notification_types": [
        "device_lost",
        "device_recovered",
        "reattach_failed",
        "app_down",
        "app_restarted",
        "app_restart_failed",
        "device_attached",
        "device_detached",
    ],
    "dependent_apps": [],
    "devices": [
        {"name": "Z-Wave Stick", "device_or_bus_id": "0658:0200"},
        {"name": "Zigbee Stick", "device_or_bus_id": "1-1.3"},
    ],
    # Default logging behavior for UI auto-scroll
    "log_auto_scroll": "when_not_paused",
}

SAMPLE_SUPERVISOR_INFO_RESPONSE = {
    "result": "ok",
    "data": {"options": SAMPLE_APP_CONFIG},
}

SAMPLE_DISCOVERY_DATA = [
    {
        "server": "192.168.1.44",
        "busid": "1-1.3",
        "name": "Silicon Labs : CP210x UART Bridge",
        "device_id": "10c4:ea60",
    },
    {
        "server": "192.168.1.44",
        "busid": "1-1.4",
        "name": "Sigma Designs, Inc. : Aeotec Z-Stick Gen5",
        "device_id": "0658:0200",
    },
]

SAMPLE_DEVICE_MANIFEST = [
    {
        "server": "192.168.1.44",
        "bus_id": "1-1.4",
        "name": "Z-Wave Stick",
        "delay": 2,
        "retries": 3,
    },
    {
        "server": "192.168.1.44",
        "bus_id": "1-1.3",
        "name": "Zigbee Stick",
        "delay": 2,
        "retries": 3,
    },
]

SAMPLE_APPS_LIST_RESPONSE = {
    "result": "ok",
    "data": {
        "addons": [
            {"slug": "45df7312_zigbee2mqtt", "name": "Zigbee2MQTT", "state": "started"},
            {"slug": "core_zwave_js", "name": "Z-Wave JS", "state": "started"},
            {"slug": "core_mosquitto", "name": "Mosquitto", "state": "stopped"},
            {
                "slug": "local_ha_usbip_client",
                "name": "HA USB/IP Client",
                "state": "started",
            },
        ]
    },
}

SAMPLE_APP_INFO_RESPONSE_STARTED = {
    "result": "ok",
    "data": {"state": "started", "slug": "45df7312_zigbee2mqtt", "name": "Zigbee2MQTT"},
}

SAMPLE_APP_INFO_RESPONSE_STOPPED = {
    "result": "ok",
    "data": {"state": "stopped", "slug": "core_zwave_js", "name": "Z-Wave JS"},
}

SAMPLE_APP_RESTART_RESPONSE = {
    "result": "ok",
    "data": {},
}
