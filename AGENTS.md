# AGENTS Guide for Home Assistant POS Printer

This repository contains a Home Assistant custom component (`custom_components/pos_printer`) and a Raspberry Pi service in the `bridge/` directory. The integration communicates with the bridge via MQTT to print on Bixolon POS printers.

## Repository Layout

- `custom_components/pos_printer` – Home Assistant integration
  - Python modules implementing the integration
  - `tests/` – pytest based unit tests
  - `translations/` – language files
- `bridge/` – standalone Python service running on a Pi
- `schema/` – JSON schema defining the job format

## Coding Conventions

- Write Python 3.8+ code and keep the existing style (type hints and docstrings).
- Choose descriptive variable and function names.
- Keep functions small and add comments for non‑trivial logic.
- Do not modify files under `public` or other unrelated directories.

## Testing

Run unit tests from the repository root with:

```bash
pytest
```

Tests cover the Home Assistant integration inside `custom_components/pos_printer/tests`.

## Pull Request Guidelines

1. Provide a short description of the changes.
2. Reference related issues if available.
3. Ensure all tests pass (`pytest`).
4. Keep each PR focused on a single topic.

## Programmatic Checks

All code contributions must pass the `pytest` suite before merge.

