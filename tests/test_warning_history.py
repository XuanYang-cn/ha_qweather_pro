"""Local 24-hour history tests for household warning source transitions."""

from datetime import datetime, timedelta, timezone

from custom_components.qweather_pro.warning_history import WarningHistory


NOW = datetime(2026, 7, 14, 8, tzinfo=timezone.utc)


def _contract(city_warning=None, district_warning=None) -> dict:
    sources = {
        "city": {"warnings": [city_warning] if city_warning else []},
        "district": {"warnings": [district_warning] if district_warning else []},
    }
    return {"sources": sources}


def _warning(level: str, text: str = "Synthetic content") -> dict:
    return {
        "hazard_id": "rain",
        "hazard_name": "Rain",
        "level": level,
        "text": text,
        "instruction": "Synthetic instruction",
    }


def test_history_records_issue_upgrade_downgrade_update_and_clear() -> None:
    history = WarningHistory("synthetic-jurisdiction")

    assert history.observe(_contract(city_warning=_warning("blue")), NOW)
    assert history.observe(
        _contract(city_warning=_warning("yellow")), NOW + timedelta(minutes=5)
    )
    assert history.observe(
        _contract(city_warning=_warning("blue")), NOW + timedelta(minutes=10)
    )
    assert history.observe(
        _contract(city_warning=_warning("blue", "Revised content")),
        NOW + timedelta(minutes=15),
    )
    assert history.observe(_contract(), NOW + timedelta(minutes=20))

    assert [event["action"] for event in history.events] == [
        "cleared",
        "updated",
        "downgraded",
        "upgraded",
        "issued",
    ]
    assert {event["source_level"] for event in history.events} == {"city"}


def test_history_restores_the_prior_source_snapshot_without_duplicate_issue() -> None:
    history = WarningHistory("synthetic-jurisdiction")
    history.observe(_contract(district_warning=_warning("yellow")), NOW)

    restored = WarningHistory.from_storage(
        history.as_storage(),
        "synthetic-jurisdiction",
        NOW + timedelta(minutes=5),
    )

    assert not restored.observe(
        _contract(district_warning=_warning("yellow")), NOW + timedelta(minutes=5)
    )
    assert [event["action"] for event in restored.events] == ["issued"]


def test_history_prunes_expired_nodes_and_resets_for_a_new_jurisdiction() -> None:
    history = WarningHistory("synthetic-jurisdiction")
    history.observe(_contract(city_warning=_warning("yellow")), NOW)
    storage = history.as_storage()

    restored = WarningHistory.from_storage(
        storage,
        "synthetic-jurisdiction",
        NOW + timedelta(hours=24, seconds=1),
    )
    changed_jurisdiction = WarningHistory.from_storage(
        storage,
        "new-synthetic-jurisdiction",
        NOW + timedelta(minutes=5),
    )

    assert restored.events == []
    assert changed_jurisdiction.events == []
