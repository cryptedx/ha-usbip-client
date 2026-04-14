"""Home Assistant Supervisor API client for reading/writing app config."""

import json
import urllib.request

from .constants import SUPERVISOR_TOKEN, SUPERVISOR_URL, WEBUI_INTERNAL_PORT


NOTIFICATION_TYPES = [
    "device_lost",
    "device_recovered",
    "reattach_failed",
    "flap_warning",
    "flap_critical",
    "app_down",
    "app_restarted",
    "app_restart_failed",
    "device_attached",
    "device_detached",
]

WEBUI_PORT_FIELD = "webui_port"
WEBUI_NETWORK_KEY = f"{WEBUI_INTERNAL_PORT}/tcp"


def _strip_virtual_config_fields(config: dict) -> tuple[dict, bool]:
    """Remove fields that are derived from Supervisor runtime state."""
    if not isinstance(config, dict):
        return {}, False
    if not config:
        return {}, False

    changed = False
    if WEBUI_PORT_FIELD in config:
        del config[WEBUI_PORT_FIELD]
        changed = True

    return config, changed


def _normalize_webui_port(value: object) -> int | None:
    """Validate direct WebUI host-port values from UI or Supervisor payloads."""
    if value is None:
        return None

    if isinstance(value, bool):
        raise ValueError(
            "Direct WebUI host port must be blank/0 to disable or an integer "
            "between 1 and 65535."
        )

    if isinstance(value, str):
        value = value.strip()
        if not value or value == "0":
            return None
        if not value.isdigit():
            raise ValueError(
                "Direct WebUI host port must be blank/0 to disable or an integer "
                "between 1 and 65535."
            )
        value = int(value)
    elif value == 0:
        return None
    elif not isinstance(value, int):
        raise ValueError(
            "Direct WebUI host port must be blank/0 to disable or an integer "
            "between 1 and 65535."
        )

    if value < 1 or value > 65535:
        raise ValueError(
            "Direct WebUI host port must be blank/0 to disable or an integer "
            "between 1 and 65535."
        )

    return value


def _get_webui_port(config_data: dict) -> int | None:
    """Read the effective direct WebUI host port from Supervisor app info."""
    if not isinstance(config_data, dict):
        return None

    network = config_data.get("network")
    if not isinstance(network, dict):
        return None

    try:
        return _normalize_webui_port(network.get(WEBUI_NETWORK_KEY))
    except ValueError:
        return None


def _build_supervisor_config_payload(options: dict) -> tuple[dict, str | None]:
    """Translate WebUI config payload into Supervisor options + network payloads."""
    if not isinstance(options, dict):
        return {}, "Configuration payload must be an object."

    normalized_options = dict(options)
    network_payload = None

    if WEBUI_PORT_FIELD in normalized_options:
        raw_webui_port = normalized_options.pop(WEBUI_PORT_FIELD)
        try:
            webui_port = _normalize_webui_port(raw_webui_port)
        except ValueError as exc:
            return {}, str(exc)
        network_payload = {WEBUI_NETWORK_KEY: webui_port}

    normalized_options, _ = normalize_dependent_apps_config(normalized_options)
    normalized_options, _ = normalize_notification_config(normalized_options)
    normalized_options, _ = _strip_virtual_config_fields(normalized_options)

    payload = {"options": normalized_options}
    if network_payload is not None:
        payload["network"] = network_payload

    return payload, None


def normalize_dependent_apps_config(config: dict) -> tuple[dict, bool]:
    """Normalize legacy dependent config key to dependent_apps."""
    if not isinstance(config, dict):
        return {}, False
    if not config:
        return {}, False

    changed = False
    apps = config.get("dependent_apps")
    legacy_apps = config.get("dependent_addons")

    if not isinstance(apps, list):
        apps = []
        config["dependent_apps"] = apps
        changed = True

    if not apps and isinstance(legacy_apps, list) and legacy_apps:
        config["dependent_apps"] = legacy_apps
        changed = True

    if "dependent_addons" in config:
        del config["dependent_addons"]
        changed = True

    return config, changed


def normalize_notification_config(config: dict) -> tuple[dict, bool]:
    """Normalize notification-related config keys and values."""
    if not isinstance(config, dict):
        return {}, False
    if not config:
        return {}, False

    changed = False

    if not isinstance(config.get("notifications_enabled"), bool):
        config["notifications_enabled"] = True
        changed = True

    notification_types = config.get("notification_types")
    if not isinstance(notification_types, list):
        config["notification_types"] = list(NOTIFICATION_TYPES)
        changed = True
    else:
        normalized_types: list[str] = []
        seen_types: set[str] = set()
        for notification_type in notification_types:
            if not isinstance(notification_type, str):
                changed = True
                continue
            if notification_type not in NOTIFICATION_TYPES:
                changed = True
                continue
            if notification_type in seen_types:
                changed = True
                continue
            seen_types.add(notification_type)
            normalized_types.append(notification_type)
        if normalized_types != notification_types:
            config["notification_types"] = normalized_types
            changed = True

    return config, changed


def get_unique_servers(config: dict) -> set[str]:
    """Collect unique USB/IP server addresses from app config."""
    if not isinstance(config, dict):
        return set()

    servers: set[str] = set()
    default_server = str(config.get("usbipd_server_address", "")).strip()
    if default_server:
        servers.add(default_server)

    devices = config.get("devices", [])
    if isinstance(devices, list):
        for device in devices:
            if not isinstance(device, dict):
                continue
            server = str(device.get("server", "")).strip()
            if server:
                servers.add(server)

    return servers


def supervisor_request(
    method: str,
    path: str,
    json_data: dict | None = None,
    token: str = SUPERVISOR_TOKEN,
    base_url: str = SUPERVISOR_URL,
) -> dict:
    """Make a request to the HA Supervisor API.

    Args:
        method: HTTP method (GET, POST, etc.).
        path: API path (e.g., /addons/self/info).
        json_data: Optional JSON body.
        token: Supervisor auth token.
        base_url: Supervisor base URL.

    Returns:
        Parsed JSON response dict.
    """
    url = f"{base_url}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    data = json.dumps(json_data).encode() if json_data else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"result": "error", "message": str(e)}


def get_app_config(
    token: str = SUPERVISOR_TOKEN, base_url: str = SUPERVISOR_URL
) -> dict:
    """Read current app options from Supervisor.

    Returns:
        Dict of app configuration options.
    """
    resp = supervisor_request(
        "GET", "/addons/self/info", token=token, base_url=base_url
    )
    if resp.get("result") == "ok":
        config_data = resp.get("data", {})
        options = config_data.get("options", {})
        if not isinstance(options, dict):
            options = {}
        else:
            options = dict(options)

        normalized, _ = normalize_dependent_apps_config(options)
        normalized, _ = normalize_notification_config(normalized)
        normalized, _ = _strip_virtual_config_fields(normalized)
        normalized[WEBUI_PORT_FIELD] = _get_webui_port(config_data)
        return normalized
    return {}


def set_app_config(
    options: dict,
    token: str = SUPERVISOR_TOKEN,
    base_url: str = SUPERVISOR_URL,
) -> dict:
    """Write app options via Supervisor.

    Args:
        options: Dict of options to set.

    Returns:
        Supervisor response dict.
    """
    payload, error = _build_supervisor_config_payload(options)
    if error:
        return {"result": "error", "message": error}

    return supervisor_request(
        "POST",
        "/addons/self/options",
        payload,
        token=token,
        base_url=base_url,
    )


def send_ha_notification(
    title: str,
    message: str,
    notification_type: str | None = None,
    bypass_type_filter: bool = False,
    token: str = SUPERVISOR_TOKEN,
    base_url: str = SUPERVISOR_URL,
) -> None:
    """Send a persistent notification to Home Assistant.

    Args:
        title: Notification title.
        message: Notification body text.
    """
    config = get_app_config(token=token, base_url=base_url)

    if not config.get("notifications_enabled", True):
        return

    if notification_type and not bypass_type_filter:
        allowed_types = config.get("notification_types", NOTIFICATION_TYPES)
        if notification_type not in allowed_types:
            return

    supervisor_request(
        "POST",
        "/core/api/services/persistent_notification/create",
        {"title": title, "message": message},
        token=token,
        base_url=base_url,
    )


# ---------------------------------------------------------------------------
# App management (dependent containers)
# ---------------------------------------------------------------------------
def list_installed_apps(
    token: str = SUPERVISOR_TOKEN, base_url: str = SUPERVISOR_URL
) -> list[dict]:
    """List all installed Home Assistant apps.

    Returns:
        List of dicts with keys: slug, name, state.
    """
    resp = supervisor_request("GET", "/addons", token=token, base_url=base_url)
    if resp.get("result") != "ok":
        return []
    app_entries = resp.get("data", {}).get("addons", [])
    return [
        {
            "slug": a.get("slug", ""),
            "name": a.get("name", ""),
            "state": a.get("state", "unknown"),
        }
        for a in app_entries
    ]


def get_app_state(
    slug: str,
    token: str = SUPERVISOR_TOKEN,
    base_url: str = SUPERVISOR_URL,
) -> str:
    """Get the state of a specific app.

    Args:
        slug: App slug (e.g., ``45df7312_zigbee2mqtt``).

    Returns:
        State string (``started``, ``stopped``, ``unknown``).
    """
    resp = supervisor_request(
        "GET", f"/addons/{slug}/info", token=token, base_url=base_url
    )
    if resp.get("result") == "ok":
        return resp.get("data", {}).get("state", "unknown")
    return "unknown"


def restart_app(
    slug: str,
    token: str = SUPERVISOR_TOKEN,
    base_url: str = SUPERVISOR_URL,
) -> bool:
    """Restart a Home Assistant app.

    Args:
        slug: App slug.

    Returns:
        True if restart was successful.
    """
    resp = supervisor_request(
        "POST", f"/addons/{slug}/restart", token=token, base_url=base_url
    )
    return resp.get("result") == "ok"
