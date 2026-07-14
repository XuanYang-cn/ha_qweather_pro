"""Same-day rain guidance boundaries."""
from datetime import datetime

from custom_components.qweather_pro.rain_guidance import daily_rain_guidance


def hour(value: str, *, pop: float = 0, precip: float = 0, icon: str = "100") -> dict:
    return {"datetime": value, "precipitation_probability": pop, "native_precipitation": precip, "icon": icon}


def test_30_percent_hits_but_29_does_not() -> None:
    now = datetime.fromisoformat("2026-07-14T10:15:00+08:00")
    assert daily_rain_guidance([hour("2026-07-14T11:00:00+08:00", pop=30)], {"state": "stale"}, now)["state"] == "rain_expected"
    assert daily_rain_guidance([hour("2026-07-14T11:00:00+08:00", pop=29)], {"state": "fresh"}, now)["state"] == "unconfirmed"


def test_tomorrow_does_not_affect_same_day_guidance() -> None:
    now = datetime.fromisoformat("2026-07-14T23:15:00+08:00")
    assert daily_rain_guidance([hour("2026-07-15T00:00:00+08:00", pop=100)], {"state": "fresh"}, now)["state"] == "no_rain_expected"


def test_only_complete_fresh_hourly_coverage_can_confirm_no_rain() -> None:
    now = datetime.fromisoformat("2026-07-14T21:15:00+08:00")
    complete = [
        hour("2026-07-14T22:00:00+08:00"),
        hour("2026-07-14T23:00:00+08:00"),
    ]
    assert daily_rain_guidance(complete, {"state": "fresh"}, now)["state"] == "no_rain_expected"
    assert daily_rain_guidance(complete[:-1], {"state": "fresh"}, now)["state"] == "unconfirmed"
    assert daily_rain_guidance(complete, {"state": "stale"}, now)["state"] == "unconfirmed"


def test_precipitation_and_rain_codes_are_sufficient_evidence() -> None:
    now = datetime.fromisoformat("2026-07-14T10:15:00+08:00")
    assert daily_rain_guidance([hour("2026-07-14T11:00:00+08:00", precip=0.1)], {"state": "stale"}, now)["state"] == "rain_expected"
    assert daily_rain_guidance([hour("2026-07-14T11:00:00+08:00", icon="302")], {"state": "stale"}, now)["state"] == "rain_expected"
