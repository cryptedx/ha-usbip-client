"""Core USB/IP operations: discover, attach, detach, parse, kernel module management."""

import json
import logging
import os
import re
import socket
import subprocess
import time

from .constants import (
    ATTACHED_DEVICES_FILE,
    BLIND_DETACH_MAX_PORT,
    DEFAULT_ATTACH_DELAY,
    DEFAULT_ATTACH_RETRIES,
    DEVICE_DETAILS_FILE,
    DEVICE_MANIFEST_FILE,
    USB_IDS_FILE,
    USBIP_PORT,
)

logger = logging.getLogger("usbip")


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------
def run_cmd(cmd: list[str], timeout: int = 15) -> tuple[int, str, str]:
    """Run a subprocess and return (returncode, stdout, stderr).

    Args:
        cmd: Command and arguments.
        timeout: Seconds before killing the process.

    Returns:
        Tuple of (return_code, stdout, stderr).
    """
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def parse_usbip_port() -> list[dict]:
    """Parse ``usbip port`` output into structured data.

    Returns:
        List of dicts with keys: port, status, info, busid, device_id,
        server, remote_busid.
    """
    rc, out, _ = run_cmd(["usbip", "port"])
    if rc != 0 or not out.strip():
        return []
    return _parse_usbip_port_output(out)


def _parse_usbip_port_output(out: str) -> list[dict]:
    """Parse raw ``usbip port`` text (testable without subprocess)."""
    devices: list[dict] = []
    current: dict | None = None
    for line in out.splitlines():
        m = re.match(r"^Port (\d+):\s*<(.+?)>\s*(.*)", line)
        if m:
            if current:
                devices.append(current)
            current = {
                "port": int(m.group(1)),
                "status": m.group(2).strip(),
                "info": m.group(3).strip(),
                "busid": "",
                "device_id": "",
                "server": "",
                "remote_busid": "",
            }
            continue
        if current:
            stripped = line.strip()
            bm = re.search(r"usbip://([^/]+)/([^\s]+)", stripped)
            if bm:
                current["server"] = bm.group(1).split(":")[0]
                current["remote_busid"] = bm.group(2)
            dm = re.search(r"([0-9a-fA-F]{4}:[0-9a-fA-F]{4})", stripped)
            if dm:
                current["device_id"] = dm.group(1)
    if current:
        devices.append(current)
    return devices


def parse_usbip_list(server: str) -> list[dict]:
    """Parse ``usbip list -r <server>`` into structured data.

    Args:
        server: Remote USB/IP server address.

    Returns:
        List of dicts with keys: busid, name, device_id, server.
    """
    rc, out, _ = run_cmd(["usbip", "list", "-r", server])
    if rc != 0:
        return []
    return _parse_usbip_list_output(out, server)


def _parse_usbip_list_output(out: str, server: str) -> list[dict]:
    """Parse raw ``usbip list`` text (testable without subprocess)."""
    devices: list[dict] = []
    for line in out.splitlines():
        m = re.match(
            r"^\s*([0-9][0-9.\-]+):\s*(.+)\s+\(([0-9a-fA-F]{4}:[0-9a-fA-F]{4})\)\s*$",
            line,
        )
        if m:
            devices.append(
                {
                    "busid": m.group(1).strip(),
                    "name": m.group(2).strip(),
                    "device_id": m.group(3).strip(),
                    "server": server,
                }
            )
    return devices


def lookup_usb_name(vendor_product: str, usb_ids_file: str = USB_IDS_FILE) -> str:
    """Resolve vendor:product from the usb.ids database.

    Args:
        vendor_product: String like ``0658:0200``.
        usb_ids_file: Path to the usb.ids file.

    Returns:
        Human-readable name, or the original string if not found.
    """
    if not os.path.exists(usb_ids_file):
        return vendor_product
    parts = vendor_product.lower().split(":")
    if len(parts) != 2:
        return vendor_product
    vid, pid = parts
    vendor_name = ""
    try:
        with open(usb_ids_file, "r", errors="replace") as f:
            in_vendor = False
            for line in f:
                if line.startswith("#") or not line.strip():
                    continue
                if not line.startswith("\t"):
                    if line[:4].lower() == vid:
                        vendor_name = line[4:].strip()
                        in_vendor = True
                        continue
                    elif in_vendor:
                        break
                elif in_vendor and line.startswith("\t") and not line.startswith(
                    "\t\t"
                ):
                    if line.strip()[:4].lower() == pid:
                        product_name = line.strip()[4:].strip()
                        return f"{vendor_name} {product_name}"
    except OSError:
        pass
    return vendor_name if vendor_name else vendor_product


# ---------------------------------------------------------------------------
# Device ID helpers
# ---------------------------------------------------------------------------
def is_device_id(value: str) -> bool:
    """Check if value is a USB device ID (``XXXX:XXXX`` hex format).

    >>> is_device_id("0658:0200")
    True
    >>> is_device_id("1-1.4")
    False
    """
    return bool(re.match(r"^[0-9a-fA-F]{4}:[0-9a-fA-F]{4}$", value))


def resolve_device_id_to_bus_id(
    server: str, device_id: str, discovery_data: list[dict]
) -> str | None:
    """Find the bus_id for a device_id on a given server.

    Args:
        server: Server address to match.
        device_id: USB device ID (e.g., ``0658:0200``).
        discovery_data: List of dicts from :func:`discover_devices`.

    Returns:
        The bus_id string, or None if not found.
    """
    for entry in discovery_data:
        if entry["server"] == server and entry["device_id"] == device_id:
            return entry["busid"]
    return None


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------
def ping_server(
    host: str, port: int = USBIP_PORT, timeout: float = 2.0
) -> float | None:
    """TCP connect probe to a USB/IP server.

    Returns:
        Latency in milliseconds, or None if unreachable.
    """
    try:
        start = time.monotonic()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        latency = (time.monotonic() - start) * 1000
        s.close()
        return round(latency, 1)
    except (OSError, socket.error):
        return None


# ---------------------------------------------------------------------------
# Kernel module management
# ---------------------------------------------------------------------------
def load_kernel_module(module: str = "vhci-hcd") -> bool:
    """Load a kernel module via modprobe and verify it is loaded.

    Args:
        module: Name of the kernel module.

    Returns:
        True if the module is loaded successfully.
    """
    logger.info("Attempting to load %s kernel module...", module)
    rc, _, err = run_cmd(["/sbin/modprobe", module])
    if rc != 0:
        logger.error(
            "Failed to load %s kernel module. Ensure it's available on the host. %s",
            module,
            err,
        )
        return False
    logger.info("Successfully loaded %s module.", module)

    # Verify
    rc, out, _ = run_cmd(["lsmod"])
    if rc == 0:
        for line in out.splitlines():
            if module.replace("-", "_") in line:
                logger.debug("Kernel module verified: %s", line.strip())
                return True
    logger.warning("Module %s loaded but not visible in lsmod.", module)
    return True  # modprobe succeeded, trust it


def remount_sysfs() -> bool:
    """Remount sysfs (required before USB/IP attach in container)."""
    rc, _, err = run_cmd(["mount", "-o", "remount", "-t", "sysfs", "sysfs", "/sys"])
    if rc != 0:
        logger.warning("Failed to remount sysfs: %s", err)
        return False
    time.sleep(0.5)
    return True


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
def discover_devices(servers: list[str]) -> list[dict]:
    """Discover available USB devices from all given servers.

    Args:
        servers: List of server IP addresses.

    Returns:
        List of dicts with keys: server, busid, name, device_id.
    """
    all_devices: list[dict] = []
    for server_ip in servers:
        logger.info("Discovering devices from server %s.", server_ip)
        devices = parse_usbip_list(server_ip)
        if not devices:
            logger.warning("No devices found on server %s.", server_ip)
        else:
            logger.info("Found %d device(s) on %s.", len(devices), server_ip)
            for d in devices:
                logger.info(
                    "  %s: %s (%s)", d["busid"], d["name"], d["device_id"]
                )
        all_devices.extend(devices)
    return all_devices


def write_device_details_file(
    devices: list[dict], filepath: str | None = None
) -> None:
    """Write discovered devices to the pipe-delimited details file.

    This maintains backward compatibility with the legacy shell format.
    """
    if filepath is None:
        filepath = DEVICE_DETAILS_FILE
    try:
        with open(filepath, "w") as f:
            for d in devices:
                f.write(
                    f"{d['server']}|{d['busid']}|{d['name']}|{d['device_id']}\n"
                )
    except OSError as e:
        logger.warning("Failed to write device details file: %s", e)


# ---------------------------------------------------------------------------
# Attach / Detach
# ---------------------------------------------------------------------------
def attach_device(
    server: str,
    bus_id: str,
    device_name: str = "",
    retries: int = DEFAULT_ATTACH_RETRIES,
    delay: int = DEFAULT_ATTACH_DELAY,
) -> bool:
    """Attach a single USB/IP device with retry logic.

    Pre-detaches the device first, then attempts to attach up to *retries*
    times with *delay* seconds between attempts.

    Args:
        server: Remote server address.
        bus_id: Bus ID on the remote server (e.g., ``1-1.4``).
        device_name: Human-readable name for logging.
        retries: Maximum number of attach attempts.
        delay: Seconds between retry attempts.

    Returns:
        True if successfully attached.
    """
    label = f"{device_name} ({bus_id})" if device_name else bus_id

    # Pre-detach (ignore errors — device may not be attached)
    run_cmd(["usbip", "detach", "-r", server, "-b", bus_id])

    for attempt in range(1, retries + 1):
        logger.debug(
            "Attaching %s from %s — attempt %d/%d", label, server, attempt, retries
        )
        rc, _, err = run_cmd(
            ["usbip", "attach", "--remote", server, "--busid", bus_id]
        )
        if rc == 0:
            logger.info("Successfully attached: %s from %s", label, server)
            return True
        logger.warning(
            "Attach attempt %d/%d failed for %s from %s: %s",
            attempt,
            retries,
            label,
            server,
            err,
        )
        if attempt < retries:
            time.sleep(delay)

    logger.error(
        "Failed to attach %s from %s after %d attempts", label, server, retries
    )
    return False


def detach_device(port: int | str) -> bool:
    """Detach a single USB/IP device by port number.

    Args:
        port: Kernel port number.

    Returns:
        True if successfully detached.
    """
    rc, _, err = run_cmd(["usbip", "detach", "-p", str(port)])
    if rc == 0:
        logger.info("Successfully detached port %s", port)
        return True
    logger.warning("Failed to detach port %s: %s", port, err)
    return False


def detach_all() -> tuple[int, int]:
    """Detach all attached USB/IP devices.

    Tries to parse ``usbip port`` for attached ports. If that fails, falls
    back to blind detach of ports 0–15.

    Returns:
        Tuple of (detached_count, failed_count).
    """
    logger.info("Detaching all USB/IP devices")
    detached = 0
    failed = 0

    rc, out, _ = run_cmd(["usbip", "port"])
    if rc != 0 or not out.strip():
        logger.warning(
            "Failed to get USB/IP port information. Attempting blind detach..."
        )
        for port in range(BLIND_DETACH_MAX_PORT + 1):
            rc2, _, _ = run_cmd(["usbip", "detach", "-p", str(port)])
            if rc2 == 0:
                detached += 1
        if detached > 0:
            logger.info("Blind detach recovered %d device(s).", detached)
        return detached, failed

    # Parse port numbers from output
    ports_info = _parse_usbip_port_output(out)
    if not ports_info:
        logger.info("No USB/IP devices currently attached.")
        return 0, 0

    port_numbers = [d["port"] for d in ports_info]
    logger.info("Found attached USB/IP ports: %s", " ".join(str(p) for p in port_numbers))

    for d in ports_info:
        port = d["port"]
        desc = d.get("info", "Unknown device")
        logger.debug("Detaching port %d: %s", port, desc)
        if detach_device(port):
            detached += 1
        else:
            failed += 1
        time.sleep(0.5)

    logger.info("Detach complete: %d detached, %d failed", detached, failed)
    return detached, failed


# ---------------------------------------------------------------------------
# Manifest (replaces generated mount_devices script)
# ---------------------------------------------------------------------------
def build_device_manifest(
    config: dict, discovery_data: list[dict]
) -> list[dict]:
    """Build a device manifest from add-on config and discovery data.

    Resolves device IDs to bus IDs and returns a list of devices ready
    to attach.

    Args:
        config: Add-on configuration dict (from Supervisor API).
        discovery_data: List of discovered devices from :func:`discover_devices`.

    Returns:
        List of dicts with keys: server, bus_id, name, delay, retries.
    """
    default_server = config.get("usbipd_server_address", "")
    attach_delay = config.get("attach_delay", DEFAULT_ATTACH_DELAY)
    devices = config.get("devices", [])
    manifest: list[dict] = []

    for i, dev in enumerate(devices):
        name = dev.get("name", f"Device {i}")
        dev_or_bus = dev.get("device_or_bus_id", "")
        server = dev.get("server") or default_server

        if not dev_or_bus:
            logger.warning("Device %d (%s): device_or_bus_id is empty, skipping", i, name)
            continue

        if not server:
            logger.warning("Device %d (%s): no server configured, skipping", i, name)
            continue

        # Resolve device_id → bus_id
        if is_device_id(dev_or_bus):
            logger.info("Device %d (%s): Detected device_id format (%s)", i, name, dev_or_bus)
            bus_id = resolve_device_id_to_bus_id(server, dev_or_bus, discovery_data)
            if not bus_id:
                logger.warning(
                    "Device %d (%s): device_id %s not found on server %s",
                    i, name, dev_or_bus, server,
                )
                continue
            logger.info(
                "Device %d (%s): Found bus_id %s for device_id %s",
                i, name, bus_id, dev_or_bus,
            )
        else:
            logger.info("Device %d (%s): Using bus_id format (%s)", i, name, dev_or_bus)
            bus_id = dev_or_bus

        manifest.append({
            "server": server,
            "bus_id": bus_id,
            "name": name,
            "delay": attach_delay,
            "retries": DEFAULT_ATTACH_RETRIES,
        })

    return manifest


def write_device_manifest(
    manifest: list[dict], filepath: str | None = None
) -> None:
    """Write device manifest to JSON file.

    Args:
        manifest: List of device dicts to write.
        filepath: Output file path.
    """
    if filepath is None:
        filepath = DEVICE_MANIFEST_FILE
    try:
        with open(filepath, "w") as f:
            json.dump(manifest, f, indent=2)
        logger.debug("Wrote device manifest with %d device(s)", len(manifest))
    except OSError as e:
        logger.error("Failed to write device manifest: %s", e)


def read_device_manifest(filepath: str | None = None) -> list[dict]:
    """Read device manifest from JSON file.

    Args:
        filepath: Input file path.

    Returns:
        List of device dicts, or empty list on failure.
    """
    if filepath is None:
        filepath = DEVICE_MANIFEST_FILE
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.error("Failed to read device manifest: %s", e)
        return []


def attach_all_from_manifest(
    manifest: list[dict],
) -> tuple[int, int]:
    """Attach all devices from the manifest.

    Args:
        manifest: List of device dicts (from :func:`read_device_manifest`).

    Returns:
        Tuple of (succeeded_count, failed_count).
    """
    succeeded = 0
    failed = 0

    for i, dev in enumerate(manifest):
        if i > 0:
            delay = dev.get("delay", DEFAULT_ATTACH_DELAY)
            time.sleep(delay)

        ok = attach_device(
            server=dev["server"],
            bus_id=dev["bus_id"],
            device_name=dev.get("name", ""),
            retries=dev.get("retries", DEFAULT_ATTACH_RETRIES),
            delay=dev.get("delay", DEFAULT_ATTACH_DELAY),
        )
        if ok:
            succeeded += 1
        else:
            failed += 1

    logger.info("%d device(s) attached, %d failed.", succeeded, failed)
    return succeeded, failed


# ---------------------------------------------------------------------------
# Cleanup helpers
# ---------------------------------------------------------------------------
def cleanup_temp_files() -> None:
    """Remove temporary state files."""
    for path in [ATTACHED_DEVICES_FILE, DEVICE_DETAILS_FILE, DEVICE_MANIFEST_FILE]:
        try:
            os.remove(path)
        except OSError:
            pass


def write_attached_devices_file(
    ports: list[int], filepath: str | None = None
) -> None:
    """Write attached port numbers to file.

    Args:
        ports: List of port numbers.
        filepath: Output file path.
    """
    if filepath is None:
        filepath = ATTACHED_DEVICES_FILE
    try:
        with open(filepath, "w") as f:
            for port in ports:
                f.write(f"{port}\n")
    except OSError as e:
        logger.warning("Failed to write attached devices file: %s", e)
