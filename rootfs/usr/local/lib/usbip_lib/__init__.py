"""usbip_lib — Shared library for HA USB/IP Client add-on."""

from .config import (
    get_addon_config,
    get_addon_state,
    list_installed_addons,
    restart_addon,
    send_ha_notification,
    set_addon_config,
    supervisor_request,
)
from .constants import (
    ATTACHED_DEVICES_FILE,
    DEVICE_DETAILS_FILE,
    DEVICE_MANIFEST_FILE,
    EVENTS_FILE,
    SUPERVISOR_TOKEN,
    SUPERVISOR_URL,
    USB_IDS_FILE,
)
from .events import now_iso, read_events, write_event
from .logging_setup import setup_logging
from .monitor import (
    attempt_reattach,
    check_dependent_addon_health,
    clear_cooldowns,
    find_missing_devices,
    is_on_cooldown,
    restart_dependent_addons,
    set_cooldown,
)
from .usbip import (
    attach_all_from_manifest,
    attach_device,
    build_device_manifest,
    cleanup_temp_files,
    detach_all,
    detach_device,
    discover_devices,
    is_device_id,
    load_kernel_module,
    lookup_usb_name,
    parse_usbip_list,
    parse_usbip_port,
    ping_server,
    read_device_manifest,
    remount_sysfs,
    resolve_device_id_to_bus_id,
    run_cmd,
    write_attached_devices_file,
    write_device_details_file,
    write_device_manifest,
)

__all__ = [
    # config
    "get_addon_config",
    "get_addon_state",
    "list_installed_addons",
    "restart_addon",
    "set_addon_config",
    "supervisor_request",
    "send_ha_notification",
    # constants
    "EVENTS_FILE",
    "DEVICE_DETAILS_FILE",
    "ATTACHED_DEVICES_FILE",
    "DEVICE_MANIFEST_FILE",
    "USB_IDS_FILE",
    "SUPERVISOR_TOKEN",
    "SUPERVISOR_URL",
    # events
    "now_iso",
    "write_event",
    "read_events",
    # logging
    "setup_logging",
    # monitor
    "find_missing_devices",
    "attempt_reattach",
    "restart_dependent_addons",
    "check_dependent_addon_health",
    "is_on_cooldown",
    "set_cooldown",
    "clear_cooldowns",
    # usbip
    "run_cmd",
    "parse_usbip_port",
    "parse_usbip_list",
    "lookup_usb_name",
    "is_device_id",
    "resolve_device_id_to_bus_id",
    "ping_server",
    "load_kernel_module",
    "remount_sysfs",
    "discover_devices",
    "write_device_details_file",
    "attach_device",
    "detach_device",
    "detach_all",
    "build_device_manifest",
    "write_device_manifest",
    "read_device_manifest",
    "attach_all_from_manifest",
    "cleanup_temp_files",
    "write_attached_devices_file",
]
