"""Synthetic contract tests for household-effective local warnings."""

from datetime import datetime

import pytest

from custom_components.qweather_pro.household_warnings import (
    WarningContractError,
    WarningJurisdiction,
    alerts_for_configured_source,
    build_household_warning_contract,
    split_household_alerts,
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


def _location(scope: str) -> dict[str, str]:
    if scope == "city":
        return {
            "id": JURISDICTION.city_id,
            "name": JURISDICTION.city_name,
            "country": JURISDICTION.country,
        }
    if scope == "district":
        return {
            "id": JURISDICTION.district_id,
            "name": JURISDICTION.district_name,
            "cityId": JURISDICTION.city_id,
            "cityName": JURISDICTION.city_name,
            "country": JURISDICTION.country,
        }
    return {
        "id": "synthetic-other-district",
        "name": "Synthetic Other District",
        "cityId": JURISDICTION.city_id,
        "cityName": JURISDICTION.city_name,
        "country": JURISDICTION.country,
    }


def _warning(
    *,
    warning_id: str = "rain-city",
    hazard_code: str = "rain",
    hazard_name: str = "暴雨",
    level: str | None = "yellow",
    title: str = "暴雨黄色预警",
    issued: str = "2026-07-14T08:00:00+08:00",
    status: str = "active",
    scope: str = "city",
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
        "administrativeLevel": scope,
        "location": _location(scope),
    }
    if level is not None:
        warning["severity"] = level
    return warning


def test_higher_district_level_wins_while_sources_stay_independently_visible() -> None:
    contract = build_household_warning_contract(
        JURISDICTION,
        city_alerts=[_warning(warning_id="rain-city", level="yellow")],
        district_alerts=[
            _warning(warning_id="rain-district", level="red", scope="district")
        ],
        now=NOW,
    )

    warning = contract["effective_warnings"][0]
    assert contract["state"] == "active"
    assert contract["jurisdiction"] == "Synthetic District · Synthetic City · Synthetic Country"
    assert warning["hazard_id"] == "rain"
    assert warning["level"] == "red"
    assert warning["source_level"] == "district"
    assert warning["source_count"] == 2
    assert contract["sources"]["city"]["state"] == "active"
    assert contract["sources"]["district"]["state"] == "active"
    assert contract["recent_changes"] == {"rain": "2026-07-14T08:00:00+08:00"}


def test_equal_levels_prefer_the_city_source() -> None:
    contract = build_household_warning_contract(
        JURISDICTION,
        city_alerts=[_warning(level="yellow")],
        district_alerts=[_warning(level="yellow", scope="district")],
        now=NOW,
    )

    assert contract["effective_warnings"][0]["source_level"] == "city"


@pytest.mark.parametrize("source_level", ["city", "district"])
def test_a_single_source_remains_the_effective_warning(source_level: str) -> None:
    city_alerts = [_warning()] if source_level == "city" else []
    district_alerts = [
        _warning(scope="district")
    ] if source_level == "district" else []

    contract = build_household_warning_contract(
        JURISDICTION,
        city_alerts=city_alerts,
        district_alerts=district_alerts,
        now=NOW,
    )

    assert contract["effective_warnings"][0]["source_level"] == source_level
    other_source = "district" if source_level == "city" else "city"
    assert contract["sources"][other_source] == {"state": "clear", "warnings": []}


def test_latest_source_event_replaces_prior_level_and_content() -> None:
    contract = build_household_warning_contract(
        JURISDICTION,
        city_alerts=[
            _warning(level="blue", title="暴雨蓝色预警"),
            _warning(
                level="yellow",
                title="暴雨黄色预警（升级）",
                issued="2026-07-14T08:15:00+08:00",
            ),
            _warning(
                level="blue",
                title="暴雨蓝色预警（降级）",
                issued="2026-07-14T08:20:00+08:00",
            ),
        ],
        district_alerts=[],
        now=NOW,
    )

    warning = contract["effective_warnings"][0]
    assert warning["level"] == "blue"
    assert warning["title"] == "暴雨蓝色预警（降级）"
    assert contract["recent_changes"] == {"rain": "2026-07-14T08:20:00+08:00"}


def test_explicit_clear_ends_one_source_without_ending_the_other() -> None:
    contract = build_household_warning_contract(
        JURISDICTION,
        city_alerts=[
            _warning(level="yellow"),
            _warning(
                level=None,
                title="暴雨预警解除",
                issued="2026-07-14T08:15:00+08:00",
                status="cancelled",
            ),
        ],
        district_alerts=[_warning(level="blue", scope="district")],
        now=NOW,
    )

    assert contract["effective_warnings"][0]["source_level"] == "district"
    assert contract["sources"]["city"] == {"state": "clear", "warnings": []}
    assert contract["sources"]["district"]["warnings"][0]["level"] == "blue"


def test_expired_events_and_a_successful_empty_snapshot_are_clear() -> None:
    expired = _warning()
    expired["expireTime"] = "2026-07-14T08:00:00+08:00"
    contract = build_household_warning_contract(
        JURISDICTION,
        city_alerts=[expired],
        district_alerts=[],
        now=NOW,
    )

    assert contract["state"] == "clear"
    assert contract["sources"] == {
        "city": {"state": "clear", "warnings": []},
        "district": {"state": "clear", "warnings": []},
    }


def test_title_level_is_a_controlled_fallback_when_structured_level_is_missing() -> None:
    contract = build_household_warning_contract(
        JURISDICTION,
        city_alerts=[_warning(level=None, title="暴雨橙色预警")],
        district_alerts=[],
        now=NOW,
    )

    assert contract["effective_warnings"][0]["level"] == "orange"


def test_provider_type_is_used_as_a_stable_hazard_code_before_name_fallback() -> None:
    warning = _warning()
    warning.pop("eventType")
    warning["type"] = "rain-event"
    warning["typeName"] = "Localized rain name"

    contract = build_household_warning_contract(
        JURISDICTION,
        city_alerts=[warning],
        district_alerts=[],
        now=NOW,
    )

    assert contract["effective_warnings"][0]["hazard_id"] == "rain-event"
    assert contract["effective_warnings"][0]["hazard_name"] == "Localized rain name"


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


def test_split_uses_structured_jurisdiction_and_excludes_an_other_district() -> None:
    city, district = split_household_alerts(
        [
            _warning(warning_id="city", scope="city"),
            _warning(warning_id="district", scope="district"),
            _warning(warning_id="other", scope="other"),
        ],
        JURISDICTION,
    )

    assert [warning["id"] for warning in city] == ["city"]
    assert [warning["id"] for warning in district] == ["district"]


def test_split_rejects_unknown_or_conflicting_applicability_atomically() -> None:
    unknown = _warning()
    unknown.pop("administrativeLevel")
    unknown.pop("location")
    bare_scope = _warning()
    bare_scope.pop("location")
    conflict = _warning(scope="city")
    conflict["location"] = _location("district")

    with pytest.raises(WarningContractError):
        split_household_alerts([unknown], JURISDICTION)
    with pytest.raises(WarningContractError):
        split_household_alerts([bare_scope], JURISDICTION)
    with pytest.raises(WarningContractError):
        split_household_alerts([conflict], JURISDICTION)


def test_source_boundary_accepts_untagged_records_and_excludes_explicitly_foreign_ones() -> None:
    untagged = _warning()
    untagged.pop("administrativeLevel")
    untagged.pop("location")

    city_alerts = alerts_for_configured_source(
        [untagged, _warning(scope="other")],
        JURISDICTION,
        "city",
    )

    assert city_alerts == [untagged]
    with pytest.raises(WarningContractError):
        alerts_for_configured_source(
            [_warning(scope="district")],
            JURISDICTION,
            "city",
        )
