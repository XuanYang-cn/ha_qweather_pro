"""Synthetic contract tests for household-effective local warnings."""

from datetime import datetime

import pytest

from custom_components.qweather_pro.household_warnings import (
    WarningContractError,
    WarningJurisdiction,
    build_household_warning_contract,
)


JURISDICTION = WarningJurisdiction(
    district_id="synthetic-district",
    district_name="Synthetic District",
    city_id="synthetic-city",
    city_name="Synthetic City",
    country="Synthetic Country",
    longitude="120.00",
    latitude="30.00",
)
NOW = datetime.fromisoformat("2026-07-14T08:30:00+08:00")


def _warning(
    *,
    warning_id: str = "rain-city",
    hazard_code: str = "rain",
    hazard_name: str = "暴雨",
    level: str | None = "yellow",
    title: str = "暴雨黄色预警",
    issued: str = "2026-07-14T08:00:00+08:00",
    status: str = "active",
) -> dict[str, object]:
    warning: dict[str, object] = {
        "id": warning_id,
        "eventType": {"id": hazard_code, "name": hazard_name},
        "headline": title,
        "description": f"{title} 正文",
        "instruction": "合成防御指南",
        "senderName": "Synthetic Meteorological Service",
        "issuedTime": issued,
        "effectiveTime": issued,
        "expireTime": "2026-07-14T12:00:00+08:00",
        "status": status,
    }
    if level is not None:
        warning["severity"] = level
    return warning


def test_higher_district_level_wins_while_both_sources_remain_visible() -> None:
    contract = build_household_warning_contract(
        JURISDICTION,
        city_alerts=[_warning(warning_id="rain-city", level="yellow")],
        district_alerts=[_warning(warning_id="rain-district", level="red")],
        now=NOW,
    )

    assert contract["state"] == "active"
    assert contract["jurisdiction"] == "Synthetic District · Synthetic City · Synthetic Country"
    assert contract["effective_warnings"] == [
        {
            "hazard_id": "rain",
            "hazard_name": "暴雨",
            "level": "red",
            "source_level": "district",
            "issued": "2026-07-14T08:00:00+08:00",
            "effective": "2026-07-14T08:00:00+08:00",
            "expires": "2026-07-14T12:00:00+08:00",
            "title": "暴雨黄色预警",
            "text": "暴雨黄色预警 正文",
            "instruction": "合成防御指南",
            "sender": "Synthetic Meteorological Service",
            "source_count": 2,
            "source": "QWeather",
        }
    ]
    assert {warning["source_level"] for warning in contract["sources"]["rain"]} == {
        "city",
        "district",
    }


def test_equal_levels_prefer_the_city_source() -> None:
    contract = build_household_warning_contract(
        JURISDICTION,
        city_alerts=[_warning(warning_id="rain-city", level="yellow")],
        district_alerts=[_warning(warning_id="rain-district", level="yellow")],
        now=NOW,
    )

    assert contract["effective_warnings"][0]["source_level"] == "city"


def test_clear_event_ends_one_source_without_ending_the_other() -> None:
    contract = build_household_warning_contract(
        JURISDICTION,
        city_alerts=[
            _warning(warning_id="rain-city", level="yellow"),
            _warning(
                warning_id="rain-city-clear",
                level=None,
                title="暴雨预警解除",
                issued="2026-07-14T08:15:00+08:00",
                status="cancelled",
            ),
        ],
        district_alerts=[_warning(warning_id="rain-district", level="blue")],
        now=NOW,
    )

    assert contract["effective_warnings"][0]["source_level"] == "district"
    assert contract["sources"]["rain"] == [
        {
            "hazard_id": "rain",
            "hazard_name": "暴雨",
            "level": "blue",
            "source_level": "district",
            "issued": "2026-07-14T08:00:00+08:00",
            "effective": "2026-07-14T08:00:00+08:00",
            "expires": "2026-07-14T12:00:00+08:00",
            "title": "暴雨黄色预警",
            "text": "暴雨黄色预警 正文",
            "instruction": "合成防御指南",
            "sender": "Synthetic Meteorological Service",
            "source": "QWeather",
        }
    ]


def test_title_level_is_a_controlled_fallback_when_structured_level_is_missing() -> None:
    contract = build_household_warning_contract(
        JURISDICTION,
        city_alerts=[_warning(level=None, title="暴雨橙色预警")],
        district_alerts=[],
        now=NOW,
    )

    assert contract["effective_warnings"][0]["level"] == "orange"


@pytest.mark.parametrize(
    "warning",
    [
        _warning(level=None, title="暴雨预警"),
        _warning(hazard_code="", hazard_name=""),
        {**_warning(), "issuedTime": "not-a-time"},
    ],
)
def test_any_unusable_applicable_record_rejects_the_whole_contract(warning) -> None:
    with pytest.raises(WarningContractError):
        build_household_warning_contract(
            JURISDICTION,
            city_alerts=[warning],
            district_alerts=[],
            now=NOW,
        )
