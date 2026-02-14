"""Monitor helper functions for USB/IP device and app health monitoring.

These are extracted from the monitor service so they can be properly
unit-tested via normal imports.
"""

import logging
import time

from .config import get_app_state, restart_app, send_ha_notification
from .events import write_event
from .usbip import attach_device


# Per-device cooldown tracking: bus_id -> last_notification_time
_notification_cooldowns: dict[str, float] = {}
COOLDOWN_SECONDS = 300  # 5 minutes

# Track previous app health to avoid repeated alerts
_app_health_prev: dict[str, str] = {}


def is_on_cooldown(device_key: str) -> bool:
    """Check if a device notification is within the cooldown window."""
    last = _notification_cooldowns.get(device_key, 0)
    return (time.monotonic() - last) < COOLDOWN_SECONDS


def set_cooldown(device_key: str) -> None:
    """Record that a notification was sent for a device."""
    _notification_cooldowns[device_key] = time.monotonic()


def clear_cooldowns() -> None:
    """Reset all notification cooldowns (useful for testing)."""
    _notification_cooldowns.clear()


def find_missing_devices(manifest: list[dict], attached: list[dict]) -> list[dict]:
    """Compare manifest against currently attached devices.

    Returns list of manifest entries that are NOT found in attached devices.
    Matching is done by server + bus_id.

    Args:
        manifest: List of device dicts from the device manifest.
        attached: List of device dicts from ``parse_usbip_port()``.

    Returns:
        List of manifest entries not found in attached devices.
    """
    attached_set = set()
    for d in attached:
        server = d.get("server", "")
        remote_busid = d.get("remote_busid", "")
        if server and remote_busid:
            attached_set.add((server, remote_busid))

    missing = []
    for dev in manifest:
        key = (dev.get("server", ""), dev.get("bus_id", ""))
        if key not in attached_set:
            missing.append(dev)
    return missing


def attempt_reattach(device: dict, retries: int, logger: logging.Logger) -> bool:
    """Try to reattach a lost device.

    Args:
        device: Manifest entry dict with server, bus_id, name, delay.
        retries: Max number of attach retries.
        logger: Logger instance.

    Returns:
        True if reattach succeeded.
    """
    server = device["server"]
    bus_id = device["bus_id"]
    name = device.get("name", bus_id)
    delay = device.get("delay", 2)

    logger.info("Attempting reattach of %s (%s) from %s", name, bus_id, server)
    write_event("reattach_attempt", f"Reattaching {name}", device=name, server=server)

    ok = attach_device(
        server=server,
        bus_id=bus_id,
        device_name=name,
        retries=retries,
        delay=delay,
    )

    if ok:
        logger.info("Successfully reattached %s (%s)", name, bus_id)
        write_event("reattach_ok", f"Reattached {name}", device=name, server=server)
    else:
        logger.error(
            "Failed to reattach %s (%s) after %d retries", name, bus_id, retries
        )
        write_event(
            "reattach_fail", f"Reattach failed for {name}", device=name, server=server
        )

    return ok


def restart_dependent_apps(
    dependent_apps: list[dict], restart_retries: int, logger: logging.Logger
) -> None:
    """Restart all configured dependent apps.

    Args:
        dependent_apps: List of dicts with 'name' and 'slug' keys.
        restart_retries: Max restart attempts per app.
        logger: Logger instance.
    """
    for app in dependent_apps:
        slug = app.get("slug", "")
        name = app.get("name", slug)
        if not slug:
            continue

        for attempt in range(1, restart_retries + 1):
            logger.info(
                "Restarting %s (%s) — attempt %d/%d",
                name,
                slug,
                attempt,
                restart_retries,
            )
            ok = restart_app(slug)
            if ok:
                logger.info("Successfully restarted %s", name)
                write_event("app_restart_ok", f"Restarted {name}", device=name)
                send_ha_notification(
                    "USB/IP: App Restarted",
                    f"{name} was restarted after USB device recovery.",
                )
                break
            logger.warning(
                "Restart attempt %d/%d failed for %s", attempt, restart_retries, name
            )
            if attempt < restart_retries:
                time.sleep(5)
        else:
            logger.error(
                "Failed to restart %s after %d attempts", name, restart_retries
            )
            write_event("app_restart_fail", f"Failed to restart {name}", device=name)
            send_ha_notification(
                "USB/IP: App Restart Failed",
                f"Could not restart {name} ({slug}) after {restart_retries} attempts.",
            )


def check_dependent_app_health(
    dependent_apps: list[dict], restart_retries: int, logger: logging.Logger
) -> None:
    """Check health of dependent apps and notify on state changes.

    Args:
        dependent_apps: List of dicts with 'name' and 'slug' keys.
        restart_retries: Max restart attempts per app.
        logger: Logger instance.
    """
    for app in dependent_apps:
        slug = app.get("slug", "")
        name = app.get("name", slug)
        if not slug:
            continue

        state = get_app_state(slug)
        prev = _app_health_prev.get(slug, "started")

        if state != "started" and prev == "started":
            logger.warning("Dependent app %s (%s) is %s", name, slug, state)
            write_event("app_health_fail", f"{name} is {state}", device=name)
            send_ha_notification(
                "USB/IP: Dependent App Down",
                f"{name} ({slug}) state: {state}. USB device may have failed.",
            )
            # Restart app if it's in error state
            if state == "error":
                logger.info("Attempting to restart failed app %s (%s)", name, slug)
                for attempt in range(1, restart_retries + 1):
                    logger.info(
                        "Restarting %s (%s) — attempt %d/%d",
                        name,
                        slug,
                        attempt,
                        restart_retries,
                    )
                    ok = restart_app(slug)
                    if ok:
                        logger.info("Successfully restarted %s", name)
                        write_event(
                            "app_restart_ok", f"Restarted {name}", device=name
                        )
                        send_ha_notification(
                            "USB/IP: App Restarted",
                            f"{name} was restarted due to error state.",
                        )
                        break
                    logger.warning(
                        "Restart attempt %d/%d failed for %s",
                        attempt,
                        restart_retries,
                        name,
                    )
                    if attempt < restart_retries:
                        time.sleep(5)
                else:
                    logger.error(
                        "Failed to restart %s after %d attempts", name, restart_retries
                    )
                    write_event(
                        "app_restart_fail", f"Failed to restart {name}", device=name
                    )
                    send_ha_notification(
                        "USB/IP: App Restart Failed",
                        f"Could not restart {name} ({slug}) after {restart_retries} attempts.",
                    )
        elif state == "started" and prev != "started":
            logger.info(
                "Dependent app %s (%s) recovered — now %s", name, slug, state
            )
            write_event("app_health_ok", f"{name} recovered", device=name)

        _app_health_prev[slug] = state
