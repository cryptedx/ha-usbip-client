"""Home Assistant Supervisor API client for reading/writing add-on config."""

import json
import urllib.request

from .constants import SUPERVISOR_TOKEN, SUPERVISOR_URL


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


def get_addon_config(
    token: str = SUPERVISOR_TOKEN, base_url: str = SUPERVISOR_URL
) -> dict:
    """Read current add-on options from Supervisor.

    Returns:
        Dict of add-on configuration options.
    """
    resp = supervisor_request(
        "GET", "/addons/self/info", token=token, base_url=base_url
    )
    if resp.get("result") == "ok":
        return resp.get("data", {}).get("options", {})
    return {}


def set_addon_config(
    options: dict,
    token: str = SUPERVISOR_TOKEN,
    base_url: str = SUPERVISOR_URL,
) -> dict:
    """Write add-on options via Supervisor.

    Args:
        options: Dict of options to set.

    Returns:
        Supervisor response dict.
    """
    return supervisor_request(
        "POST",
        "/addons/self/options",
        {"options": options},
        token=token,
        base_url=base_url,
    )


def send_ha_notification(
    title: str,
    message: str,
    token: str = SUPERVISOR_TOKEN,
    base_url: str = SUPERVISOR_URL,
) -> None:
    """Send a persistent notification to Home Assistant.

    Args:
        title: Notification title.
        message: Notification body text.
    """
    supervisor_request(
        "POST",
        "/core/api/services/persistent_notification/create",
        {"title": title, "message": message},
        token=token,
        base_url=base_url,
    )


# ---------------------------------------------------------------------------
# Add-on management (dependent containers)
# ---------------------------------------------------------------------------
def list_installed_addons(
    token: str = SUPERVISOR_TOKEN, base_url: str = SUPERVISOR_URL
) -> list[dict]:
    """List all installed Home Assistant add-ons.

    Returns:
        List of dicts with keys: slug, name, state.
    """
    resp = supervisor_request("GET", "/addons", token=token, base_url=base_url)
    if resp.get("result") != "ok":
        return []
    addons = resp.get("data", {}).get("addons", [])
    return [
        {
            "slug": a.get("slug", ""),
            "name": a.get("name", ""),
            "state": a.get("state", "unknown"),
        }
        for a in addons
    ]


def get_addon_state(
    slug: str,
    token: str = SUPERVISOR_TOKEN,
    base_url: str = SUPERVISOR_URL,
) -> str:
    """Get the state of a specific add-on.

    Args:
        slug: Add-on slug (e.g., ``45df7312_zigbee2mqtt``).

    Returns:
        State string (``started``, ``stopped``, ``unknown``).
    """
    resp = supervisor_request(
        "GET", f"/addons/{slug}/info", token=token, base_url=base_url
    )
    if resp.get("result") == "ok":
        return resp.get("data", {}).get("state", "unknown")
    return "unknown"


def restart_addon(
    slug: str,
    token: str = SUPERVISOR_TOKEN,
    base_url: str = SUPERVISOR_URL,
) -> bool:
    """Restart a Home Assistant add-on.

    Args:
        slug: Add-on slug.

    Returns:
        True if restart was successful.
    """
    resp = supervisor_request(
        "POST", f"/addons/{slug}/restart", token=token, base_url=base_url
    )
    return resp.get("result") == "ok"
