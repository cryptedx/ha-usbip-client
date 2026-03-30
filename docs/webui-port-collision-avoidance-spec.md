# WebUI Port Collision Avoidance Specification

Status: Proposed
Date: 2026-03-30

## Summary

The app currently runs its WebUI on internal port 8099 and also uses `host_network: true`.
That makes the internal WebUI port identical to the host port. As a result, the app can
collide with any other Home Assistant app or host process that also listens on port 8099.

The fix is to separate the internal Ingress port from optional host exposure:

- Keep the WebUI internal port fixed at 8099 for Home Assistant Ingress.
- Remove `host_network: true`.
- Expose direct WebUI access only through explicit `ports` mapping.
- Disable direct host exposure by default.

This preserves Ingress behavior while removing the default host-level port collision.

## Current State

- `config.yaml` enables `ingress: true` with `ingress_port: 8099`.
- `config.yaml` also sets `host_network: true`.
- The WebUI service starts Flask-Socket.IO on `0.0.0.0:8099`.
- Because the app uses the host network namespace, binding `0.0.0.0:8099` binds the host
  port directly.
- Any other app or host service that also uses port 8099 can block startup or make behavior
  non-deterministic.

Observed repository drift:

- The current source binds the WebUI to 8099 unconditionally.
- The current source does not contain working implementation for a configurable direct WebUI
  host port.
- Repository documentation currently overstates direct WebUI port configurability and should
  be aligned with the real behavior during this change.

## Root Cause

The collision is not caused by Home Assistant Ingress.

Ingress proxies requests to the app's internal port and does not require a public host port.
The collision is caused by using the host network namespace for the WebUI listener.

As long as `host_network: true` remains enabled, internal port 8099 is also a host port.
Changing the internal port to another fixed value would only move the collision to a different
host port and would not solve the actual problem.

## Goals

- Eliminate host-level port 8099 collisions in the default installation.
- Keep Home Assistant Ingress working on internal port 8099.
- Preserve optional direct browser access for advanced users.
- Keep the change minimal and reversible.
- Avoid new custom networking logic unless it is strictly necessary.

## Non-Goals

- Do not redesign the USB/IP attach, detach, or monitor flow.
- Do not introduce a dynamic internal WebUI port.
- Do not move Ingress away from port 8099.
- Do not implement custom in-app port mapping controls in this change.

## Target Design

### Network Model

- The app runs on the default container network, not on the host network.
- The WebUI continues to listen on `0.0.0.0:8099` inside the container.
- Home Assistant Ingress continues to proxy to internal port 8099.
- Direct host access becomes an explicit port publication decision instead of an implicit side
  effect of `host_network: true`.

### Default Behavior

- Ingress works out of the box.
- No host port is claimed by default for the WebUI.
- A fresh install cannot collide with another app that uses host port 8099.

### Optional Direct Access

- Direct WebUI access is supported through Home Assistant port mapping.
- The app manifest declares `ports` and `ports_description` for `8099/tcp`.
- The default mapping value is `null`, which keeps direct host access disabled unless the user
  explicitly enables it in Home Assistant.

Recommended manifest shape:

```yaml
ingress: true
ingress_port: 8099
ports:
  8099/tcp: null
ports_description:
  8099/tcp: Direct WebUI access
```

`host_network: true` must be removed.

## Implementation Scope

### 1. Manifest Changes

File: `config.yaml`

Required changes:

- Remove `host_network: true`.
- Add `ports` with `8099/tcp: null`.
- Add `ports_description` for `8099/tcp` if not already present.
- Keep `ingress: true` and `ingress_port: 8099` unchanged.

Rationale:

- Home Assistant documents `ports` as the supported way to expose container ports.
- A `null` host port disables the mapping by default.
- `ingress_port` remains the stable internal target for the Ingress proxy.

### 2. Runtime Code Changes

Files:

- `rootfs/usr/local/bin/webui/app.py`
- `rootfs/etc/services.d/webui/run`
- `rootfs/usr/local/lib/usbip_lib/constants.py` if log or naming cleanup is needed

Required changes:

- Keep the WebUI bind port at internal 8099.
- Update log messages to describe 8099 as an internal port, not a guaranteed host port.
- Do not add logic that assumes direct access is always available on `http://<host>:8099`.

No other runtime networking changes are required for the collision fix itself.

### 3. WebUI and API Changes

Files:

- `rootfs/usr/local/bin/webui/templates/index.html`
- `rootfs/usr/local/bin/webui/static/app.js`
- `rootfs/usr/local/bin/webui/app.py`

Required behavior:

- Remove or reword any UI text that claims the direct WebUI port is configurable inside the
  app if that is not actually implemented.
- If the UI shows a direct-access URL, make it conditional and clearly label it as optional.
- Do not accept or advertise unsupported fields such as `webui_port` unless a verified,
  implemented persistence path exists.

This change should prefer accuracy over feature ambition.

### 4. Documentation Changes

Files:

- `README.md`
- `DEVELOPER.md`
- any WebUI-facing help text that references direct access

Required changes:

- State that Ingress always uses the internal app port.
- State that direct WebUI access is optional and depends on explicit host port mapping.
- Remove statements that imply host port 8099 is always available.
- Update developer validation steps so direct mode uses the configured host mapping, not a
  hard-coded assumption of `:8099`.

## Migration Strategy

This is a breaking runtime packaging change because `config.yaml` changes.

Expected effects:

- Existing users who relied on `http://<ha-host>:8099` will lose direct access after upgrade
  until they explicitly enable a host port mapping.
- Ingress continues to work without user action.

Required migration communication:

- Add a changelog entry that direct host access is now opt-in.
- Explain that this prevents host port collisions.
- Tell users to configure a host port in Home Assistant if they still want direct browser
  access outside Ingress.

## Risks and Validation Focus

Primary risk:

- Removing `host_network` could affect any behavior that unintentionally depended on the host
  network namespace.

Validation focus:

- USB/IP attach and detach still work against the configured remote server.
- Monitor re-attach still works.
- WebUI works via Ingress.
- Optional direct access works when a host port is explicitly mapped.
- No host listener exists on 8099 when direct mapping is disabled.

## Test Plan

### Targeted automated checks

- Add or update tests around any UI text or API payloads changed for direct access messaging.
- Add or update tests to ensure unsupported config fields are not silently advertised as
  effective settings.
- If any config helper is introduced for direct access state, add unit tests for enabled,
  disabled, and malformed values.

### Required local quality gates

Run from repository root:

```bash
.venv/bin/pre-commit run --all-files
PYTHONPATH=./rootfs/usr/local/lib .venv/bin/python -m pytest -q
.venv/bin/python scripts/check_version_consistency.py
```

## Runtime Validation Runbook

Because `config.yaml` changes, validation must include uninstall/install, not only rebuild.

Required validation sequence:

```bash
ha apps stop local_ha_usbip_client
ha apps uninstall local_ha_usbip_client
ha apps install local_ha_usbip_client
ha apps start local_ha_usbip_client
ha apps info local_ha_usbip_client
ha apps logs local_ha_usbip_client --follow
```

Validation checklist:

- Confirm the app starts successfully.
- Confirm Ingress opens and the WebUI loads.
- Confirm no host process listens on port 8099 when direct mapping is disabled.
- Configure an explicit host port mapping in Home Assistant.
- Restart the app and confirm direct access works on the configured host port.
- Confirm USB/IP device attach, detach, and monitor recovery still work.

## Acceptance Criteria

- A fresh install does not claim host port 8099.
- Ingress still works without any user port configuration.
- Direct WebUI access is disabled by default and can be enabled explicitly through Home
  Assistant port mapping.
- Repository docs no longer claim a direct host port feature that is not implemented.
- Local quality gates pass.
- Runtime validation passes in Home Assistant.

## Follow-Up Work

Not part of this change, but reasonable later if still needed:

- Add a separate, verified design for reading and writing direct host port mappings through the
  Supervisor API.
- Surface direct access state in the WebUI only after the persistence path is confirmed and
  tested.
