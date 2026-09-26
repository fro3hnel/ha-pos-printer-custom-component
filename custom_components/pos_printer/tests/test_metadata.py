"""Tests for integration metadata, translations, and bundled blueprints."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[3]
INTEGRATION = ROOT / "custom_components" / "pos_printer"


class BlueprintLoader(yaml.SafeLoader):
    """YAML loader that preserves Home Assistant blueprint inputs."""


BlueprintLoader.add_constructor(
    "!input", lambda loader, node: loader.construct_scalar(node)
)


def test_translation_files_use_home_assistant_structure():
    """Translations should not contain a legacy domain wrapper."""
    strings = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
    for language in ("en", "de"):
        translated = json.loads(
            (INTEGRATION / "translations" / f"{language}.json").read_text(
                encoding="utf-8"
            )
        )
        assert "pos_printer" not in translated
        assert "entity" in translated
        assert set(strings["entity"]) <= set(translated["entity"])
        assert set(strings["exceptions"]) <= set(translated["exceptions"])
        assert translated["entity"]["sensor"]["last_job_status"]["state"]["duplicate"]


def test_hacs_metadata_declares_tested_home_assistant_floor():
    """HACS should not offer the integration to untested legacy HA releases."""
    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    assert hacs["homeassistant"] == "2025.11.0"


def test_icons_cover_entities_without_device_class_icons():
    """Static entity icons should come from icon translations."""
    icons = json.loads((INTEGRATION / "icons.json").read_text(encoding="utf-8"))
    assert icons["entity"]["sensor"]["last_job_status"]["state"]["success"]
    assert (
        icons["entity"]["sensor"]["last_job_status"]["state"]["duplicate"]
        == "mdi:content-duplicate"
    )
    assert icons["entity"]["button"]["bridge_restart"]["default"] == "mdi:restart"


def test_job_id_limit_is_documented_for_every_action():
    """The protocol schema and action editor should expose one consistent limit."""
    protocol_schema = json.loads(
        (ROOT / "schema" / "job.schema.json").read_text(encoding="utf-8")
    )
    assert protocol_schema["properties"]["job_id"]["maxLength"] == 128

    services = yaml.safe_load(
        (INTEGRATION / "services.yaml").read_text(encoding="utf-8")
    )
    for action in ("print", "print_text", "print_image", "print_pictograms"):
        description = services[action]["fields"]["job_id"]["description"]
        assert "128" in description
        assert "new ID" in description


def test_blueprints_use_modern_syntax_and_select_config_entries():
    """Bundled blueprints should parse and avoid free-text targeting for new flows."""
    blueprint_paths = sorted(
        (ROOT / "blueprints" / "automation" / "pos_printer").glob("*.yaml")
    )
    assert len(blueprint_paths) == 5

    for path in blueprint_paths:
        raw = path.read_text(encoding="utf-8")
        parsed = yaml.load(raw, Loader=BlueprintLoader)
        assert parsed["blueprint"]["homeassistant"]["min_version"]
        assert "actions" in parsed
        assert "service:" not in raw

    generic = yaml.load(
        (
            ROOT
            / "blueprints"
            / "automation"
            / "pos_printer"
            / "print_text_on_trigger.yaml"
        ).read_text(encoding="utf-8"),
        Loader=BlueprintLoader,
    )
    selector = generic["blueprint"]["input"]["printer_config_entry"]["selector"]
    assert selector["config_entry"]["integration"] == "pos_printer"

    clothing = yaml.load(
        (
            ROOT
            / "blueprints"
            / "automation"
            / "pos_printer"
            / "print_clothing_recommendation.yaml"
        ).read_text(encoding="utf-8"),
        Loader=BlueprintLoader,
    )
    basic_inputs = clothing["blueprint"]["input"]["basic_settings"]["input"]
    assert basic_inputs["weather_entity"]["selector"]["entity"]["filter"] == [
        {"domain": "weather"}
    ]
    assert (
        basic_inputs["printer_config_entry"]["selector"]["config_entry"]["integration"]
        == "pos_printer"
    )
    assert clothing["mode"] == "queued"
    assert "weather.get_forecasts" in clothing["actions"][0]["action"]
    assert "pos_printer.print_pictograms" in clothing["actions"][-1]["action"]
