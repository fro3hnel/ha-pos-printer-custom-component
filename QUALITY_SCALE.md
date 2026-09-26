# Home Assistant Quality Scale self-audit

Audit date: 2026-07-18

This repository is a HACS custom integration, so Home Assistant displays it in
the **Custom** category and does not assign an official Bronze/Silver/Gold/
Platinum badge. The checklist below is a self-assessment against the current
[Integration Quality Scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/).
An official tier would require inclusion in Home Assistant Core and review by
the Core team.

## Defensible current position

The implementation is technically close to Gold and meets the Silver runtime
and coverage expectations. It cannot honestly claim a complete formal tier yet:

- `brands` is still open and blocks a complete Bronze checklist. Official brand
  assets must be contributed to the Home Assistant brands repository.
- `async-dependency` and `strict-typing` remain open, so Platinum is not claimed.
- Core inclusion has additional architectural/review requirements beyond this
  repository's `quality_scale.yaml`.

The integration package currently has 96% measured line coverage. The full
repository number is lower because the hardware/OS bridge and image builder need
more integration tests.

## Implemented quality work

### User experience

- MQTT discovery creates one config entry per retained per-printer topic.
- Actions select a config entry instead of requiring a typed MQTT identifier.
- The legacy `printer_name` action field remains for compatibility.
- Per-printer paper width and feed defaults are available through Configure.
- MQTT identity is treated as stable; friendly naming remains a safe HA device
  rename.
- Entity names, state values, errors, and icons use the HA translation systems.
- Diagnostic/noisy entities and the bridge-service restart are disabled by
  default; unsafe host update controls were removed.
- Four importable blueprints cover dashboard text, camera snapshots, arbitrary
  trigger text, and to-do/shopping lists.

### Reliability

- MQTT last-will availability marks entities unavailable and logs each offline/
  recovered transition once.
- Known-offline bridges reject print actions, preventing silently lost jobs.
- The bridge publishes `queued`, `printing`, and final status acknowledgements.
- Redis atomically creates a per-printer 24-hour SHA-256 job-ID marker and queue
  entry, preventing MQTT QoS 1 redelivery from producing duplicate printouts.
- Job expiry is enforced on the bridge before physical output.
- The successful-job total is persisted in Redis and survives HA restarts.
- Legacy retained MQTT sensor discovery is removed to prevent duplicate devices.
- Image input is constrained to 10 MiB and 40 megapixels.
- Diagnostics are redacted and repair issues cover invalid identities and bridge
  version drift.

### Maintainability

- Config-entry runtime data has a typed alias and common entity behavior lives in
  `entity.py`.
- Config flow, lifecycle, actions, image processing, diagnostics, repairs,
  entities, metadata, bridge discovery, and release tooling have automated tests.
- Service validation and execution failures carry translation metadata.
- CI checks Ruff, Python 3.13/3.14, pytest, a real Redis service, and a 95%
  integration coverage gate.

## Priority roadmap

### P0 — release safety

1. Release integration and bridge together because the per-printer discovery
   topic, availability LWT, status lifecycle, deduplication, and persistent
   counter are a protocol pair. Older clients stay wire-compatible but may show
   the new `duplicate` status as unknown.
2. Test upgrade, fresh install, multi-printer discovery, bridge loss/reconnect,
   queue persistence, and image printing against a real broker/Redis/printer lab.
3. Add a migration note that old duplicate MQTT sensor entities are removed by
   the updated bridge.

### P1 — highest Quality Scale return

1. Submit icon/logo assets to `home-assistant/brands` to close the remaining
   Bronze blocker.
2. Extend the pytest, coverage, Ruff, and Python-version CI with mypy and HACS
   validation.
3. Enable strict mypy checking and remove the remaining broadly typed payload and
   callback surfaces.
4. Add an MQTT broker integration-test container and test the full job lifecycle,
   reconnects, retained discovery cleanup, expiry, and command topics. Redis
   protocol behavior is already covered against a real service.

### P2 — user-facing capabilities

1. Add capability negotiation in discovery: model, paper width, supported
   barcodes, image width, heartbeat interval, and verified printer-status flags.
2. Expose paper-out, cover-open, and hardware-error binary sensors only after the
   Bixolon status bitmask is verified on supported models.
3. Add an optional action that waits for the correlated final acknowledgement
   with a timeout and returns structured status. Keep normal fire-and-track
   actions lightweight.
4. Add queue cancellation/clear operations only with explicit confirmation,
   audit logging, and job correlation.
5. Implement narrowly bounded retry rules only for failures known to occur before
   paper output; indiscriminate retries risk duplicate receipts.

### P3 — bridge lifecycle

1. Design a signed, atomic bridge update channel with rollback before exposing
   any update entity again; manual reinstall is the supported path today.
2. Keep Pi OS package management outside MQTT and document a managed image or
   SSH-based maintenance flow.
3. Harden the bridge service with documented MQTT TLS/ACL examples, least-
   privilege sudo rules, and a threat-model/security document.

## Features deliberately not added

- CPU temperature, free memory, and every bridge log field as enabled entities:
  these add noise and belong in diagnostics unless a concrete user action depends
  on them.
- A blueprint for every imaginable printout: a small set of composable blueprints
  is easier to understand and maintain.
- Automatic retry of all failed jobs: a POS printer may already have produced
  partial paper output, so generic retries can create duplicates.
- In-place MQTT identity rename: it changes the device's topic namespace and is
  better modeled as replacing one printer identity with another.
