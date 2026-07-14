"""Same-day rain guidance boundaries."""
from datetime import datetime

import pytest

from custom_components.qweather_pro.rain_guidance import daily_rain_guidance


def hour(
    value: str,
    *,
    pop: float = 0,
    precip: float = 0,
    icon: str = "100",
) -> dict[str, object]:
    return {
        "datetime": value,
        "precipitation_probability": pop,
        "native_precipitation": precip,
        "icon": icon,
    }


def hours_until_day_end(
    *,
    date: str = "2026-07-14",
    first_hour: int = 10,
) -> list[dict[str, object]]:
    return [
        hour(f"{date}T{forecast_hour:02d}:00:00+08:00")
        for forecast_hour in range(first_hour, 24)
    ]


def test_30_percent_hits_but_29_does_not() -> None:
    now = datetime.fromisoformat("2026-07-14T10:15:00+08:00")
    assert (
        daily_rain_guidance(
            [hour("2026-07-14T11:00:00+08:00", pop=30)],
            {"state": "stale"},
            now,
        )["state"]
        == "rain_expected"
    )
    no_rain = hours_until_day_end()
    no_rain[0] = hour("2026-07-14T10:00:00+08:00", pop=29)
    assert daily_rain_guidance(no_rain, {"state": "fresh"}, now)["state"] == (
        "no_rain_expected"
    )


def test_tomorrow_does_not_affect_same_day_guidance() -> None:
    now = datetime.fromisoformat("2026-07-14T10:15:00+08:00")
    assert (
        daily_rain_guidance(
            [
                *hours_until_day_end(),
                hour("2026-07-15T00:00:00+08:00", pop=100),
            ],
            {"state": "fresh"},
            now,
        )["state"]
        == "no_rain_expected"
    )


def test_current_partial_hour_requires_forecast_coverage() -> None:
    now = datetime.fromisoformat("2026-07-14T23:15:00+08:00")
    assert (
        daily_rain_guidance([], {"state": "fresh"}, now)["state"]
        == "unconfirmed"
    )
    assert (
        daily_rain_guidance(
            [hour("2026-07-14T23:00:00+08:00", icon="305")],
            {"state": "stale"},
            now,
        )["state"]
        == "rain_expected"
    )


def test_only_complete_fresh_hourly_coverage_can_confirm_no_rain() -> None:
    now = datetime.fromisoformat("2026-07-14T21:15:00+08:00")
    complete = [
        hour("2026-07-14T21:00:00+08:00"),
        hour("2026-07-14T22:00:00+08:00"),
        hour("2026-07-14T23:00:00+08:00"),
    ]
    assert (
        daily_rain_guidance(complete, {"state": "fresh"}, now)["state"]
        == "no_rain_expected"
    )
    assert (
        daily_rain_guidance(complete[:-1], {"state": "fresh"}, now)["state"]
        == "unconfirmed"
    )
    assert (
        daily_rain_guidance(complete, {"state": "stale"}, now)["state"]
        == "unconfirmed"
    )


def test_precipitation_and_rain_codes_are_sufficient_evidence() -> None:
    now = datetime.fromisoformat("2026-07-14T10:15:00+08:00")
    assert (
        daily_rain_guidance(
            [hour("2026-07-14T11:00:00+08:00", precip=0.1)],
            {"state": "stale"},
            now,
        )["state"]
        == "rain_expected"
    )
    assert (
        daily_rain_guidance(
            [hour("2026-07-14T11:00:00+08:00", icon="302")],
            {"state": "stale"},
            now,
        )["state"]
        == "rain_expected"
    )


def test_only_the_expected_hour_timestamps_can_confirm_no_rain() -> None:
    now = datetime.fromisoformat("2026-07-14T10:00:00+08:00")
    expected = hours_until_day_end(first_hour=10)
    assert (
        daily_rain_guidance(expected, {"state": "fresh"}, now)["state"]
        == "no_rain_expected"
    )
    wrong_hours = [hour("2026-07-14T09:00:00+08:00"), *expected[:-1]]
    assert (
        daily_rain_guidance(wrong_hours, {"state": "fresh"}, now)["state"]
        == "unconfirmed"
    )


def test_shanghai_local_date_controls_the_forecast_window() -> None:
    now = datetime.fromisoformat("2026-07-14T16:15:00+00:00")
    hourly = [
        hour("2026-07-14T23:00:00+08:00", pop=100),
        *hours_until_day_end(date="2026-07-15", first_hour=0),
    ]
    assert (
        daily_rain_guidance(hourly, {"state": "fresh"}, now)["state"]
        == "no_rain_expected"
    )
@pytest.mark.parametrize(
    "invalid_hour",
    [
        hour("2026-07-14T11:00:00+08:00", icon="not-a-qweather-code"),
        hour("2026-07-14T10:00:00+08:00", icon="999"),
        {"datetime": "invalid-time", "icon": "100"},
        {"datetime": "2026-07-14T10:00:00+08:00", "icon": None},
    ],
)
def test_uninterpretable_hourly_data_never_confirms_no_rain(
    invalid_hour: dict[str, object],
) -> None:
    now = datetime.fromisoformat("2026-07-14T10:15:00+08:00")
    hourly = hours_until_day_end()
    hourly[0] = invalid_hour
    assert (
        daily_rain_guidance(hourly, {"state": "fresh"}, now)["state"]
        == "unconfirmed"
    )
