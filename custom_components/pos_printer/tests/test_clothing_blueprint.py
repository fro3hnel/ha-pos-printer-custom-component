"""Behavior tests for the clothing recommendation blueprint templates."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest
import yaml
from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.blueprint.models import Blueprint
from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template
from homeassistant.util import dt as dt_util
from homeassistant.util.yaml.loader import load_yaml

ROOT = Path(__file__).parents[3]
BLUEPRINT_PATH = (
    ROOT
    / "blueprints"
    / "automation"
    / "pos_printer"
    / "print_clothing_recommendation.yaml"
)


class BlueprintLoader(yaml.SafeLoader):
    """YAML loader that preserves Home Assistant blueprint inputs."""


BlueprintLoader.add_constructor(
    "!input", lambda loader, node: loader.construct_scalar(node)
)

BLUEPRINT = yaml.load(
    BLUEPRINT_PATH.read_text(encoding="utf-8"), Loader=BlueprintLoader
)
RECOMMENDATION_TEMPLATE = BLUEPRINT["actions"][2]["variables"]["recommendation"]
WEATHER_SUBTITLE_TEMPLATE = BLUEPRINT["actions"][3]["variables"]["weather_subtitle"]


def _target_day() -> date:
    """Match the blueprint's current-or-next-day window selection."""
    current = dt_util.now()
    return current.date() + timedelta(days=1 if current.time() >= time(17) else 0)


def test_blueprint_passes_home_assistant_schema_validation():
    """The complete file should remain importable by Home Assistant."""
    blueprint = Blueprint(
        load_yaml(BLUEPRINT_PATH),
        path=str(BLUEPRINT_PATH),
        expected_domain="automation",
        schema=AUTOMATION_BLUEPRINT_SCHEMA,
    )

    assert blueprint.domain == "automation"


def _forecast_rows(temperatures, condition="sunny", rain_probability=0):
    """Build hourly-like forecast rows inside the default daytime window."""
    target_day = _target_day()
    hours = (8, 15)
    return [
        {
            "datetime": datetime.combine(
                target_day, time(hour), tzinfo=dt_util.DEFAULT_TIME_ZONE
            ).isoformat(),
            "temperature": temperature,
            "condition": condition,
            "precipitation_probability": rain_probability,
        }
        for hour, temperature in zip(hours, temperatures, strict=True)
    ]


def _render_recommendation(hass, forecast_rows, temperature_unit="°C"):
    """Render the blueprint recommendation with its documented defaults."""
    weather_entity = "weather.test_home"
    hass.states.async_set(
        weather_entity,
        "sunny",
        {"temperature_unit": temperature_unit},
    )
    return Template(RECOMMENDATION_TEMPLATE, hass).async_render(
        {
            "forecast_rows": forecast_rows,
            "weather_entity": weather_entity,
            "window_start": "07:00:00",
            "window_end": "17:00:00",
            "selected_rain_gear": "coat_boots",
            "t_shirt_threshold": 18,
            "shorts_min_threshold": 16,
            "shorts_max_threshold": 22,
            "sweater_threshold": 16,
            "light_jacket_threshold": 12,
            "winter_threshold": 5,
            "rain_threshold": 40,
        },
        parse_result=True,
    )


@pytest.mark.parametrize(
    ("forecast_rows", "expected"),
    [
        (
            _forecast_rows((20, 27)),
            ["t_shirt", "shorts", "sneakers"],
        ),
        (
            _forecast_rows((8, 14)),
            [
                "long_sleeve",
                "trousers",
                "sweater",
                "light_jacket",
                "sneakers",
            ],
        ),
        (
            _forecast_rows((10, 18), condition="rainy", rain_probability=60),
            ["t_shirt", "trousers", "sweater", "raincoat", "rain_boots"],
        ),
        (
            _forecast_rows((2, 4), condition="snowy", rain_probability=20),
            [
                "long_sleeve",
                "trousers",
                "sweater",
                "winter_coat",
                "beanie",
                "gloves",
                "winter_boots",
            ],
        ),
    ],
)
@pytest.mark.asyncio
async def test_clothing_scenarios(tmp_path, forecast_rows, expected):
    """Default thresholds should produce the planned seasonal outfits."""
    hass = HomeAssistant(str(tmp_path))
    recommendation = _render_recommendation(hass, forecast_rows)

    assert recommendation["valid"] is True
    assert recommendation["pictograms"] == expected
    await hass.async_stop(force=True)


@pytest.mark.asyncio
async def test_fahrenheit_forecast_matches_celsius_recommendation(tmp_path):
    """Forecast temperatures should be normalized to Celsius before decisions."""
    hass = HomeAssistant(str(tmp_path))
    recommendation = _render_recommendation(
        hass,
        _forecast_rows((68, 80.6)),
        temperature_unit="°F",
    )

    assert recommendation["pictograms"] == ["t_shirt", "shorts", "sneakers"]
    assert recommendation["minimum"] == pytest.approx(20)
    assert recommendation["maximum"] == pytest.approx(27)
    await hass.async_stop(force=True)


@pytest.mark.asyncio
async def test_empty_forecast_prints_unknown_pictogram(tmp_path):
    """Missing or failed hourly forecasts should select the planned fallback."""
    hass = HomeAssistant(str(tmp_path))
    recommendation = _render_recommendation(hass, [])

    assert recommendation["valid"] is False
    assert recommendation["pictograms"] == ["unknown"]
    await hass.async_stop(force=True)


@pytest.mark.asyncio
async def test_weather_summary_uses_compact_documented_header(tmp_path):
    """The weather header should render as one small, separator-based line."""
    hass = HomeAssistant(str(tmp_path))
    subtitle = Template(WEATHER_SUBTITLE_TEMPLATE, hass).async_render(
        {
            "recommendation": {
                "valid": True,
                "date": "21.07.2026",
                "minimum": 12,
                "maximum": 22,
                "rain_probability": 40,
                "rainy": True,
            },
            "show_summary": True,
            "window_start": "07:00:00",
            "window_end": "17:00:00",
        },
        parse_result=True,
    )

    assert subtitle == "21.07.2026 · 07:00–17:00 · 12–22 °C · Regen: 40 %"
    await hass.async_stop(force=True)
