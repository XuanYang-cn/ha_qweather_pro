"""Conservative same-day rain guidance derived from hourly forecasts."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from math import isfinite
from zoneinfo import ZoneInfo

from .condition import CONDITION_MAP

SHANGHAI = ZoneInfo("Asia/Shanghai")
RAIN_STATES = frozenset({"rain_expected", "no_rain_expected", "unconfirmed"})
RAIN_ICON_CODES = frozenset(
    str(code) for code in (*range(300, 319), 350, 351, 399)
)
RAIN_CONDITIONS = frozenset(
    {"rainy", "pouring", "lightning-rainy", "snowy-rainy"}
)


def _as_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result if result.tzinfo else None


def _is_positive_number(value: object) -> bool:
    """Return whether a provider number is finite and above zero."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(value)
        and value > 0
    )


def _has_rain_evidence(hour: Mapping[str, object]) -> bool:
    """Return true only for an explicit probability, amount, or rain code."""
    probability = hour.get("precipitation_probability")
    precipitation = hour.get("native_precipitation")
    condition = hour.get("condition")
    return (
        _is_positive_number(probability) and probability >= 30
    ) or (
        _is_positive_number(precipitation)
    ) or str(hour.get("icon")) in RAIN_ICON_CODES or condition in RAIN_CONDITIONS


def _first_remaining_hour(now: datetime) -> datetime:
    """Return the first forecast hour whose value is still relevant."""
    hour_start = now.replace(minute=0, second=0, microsecond=0)
    return hour_start if now == hour_start else hour_start + timedelta(hours=1)


def _expected_hours(start: datetime, end: datetime) -> set[datetime]:
    """List every forecast-hour timestamp required to prove no rain today."""
    expected: set[datetime] = set()
    cursor = start
    while cursor <= end:
        expected.add(cursor)
        cursor += timedelta(hours=1)
    return expected


def _has_interpretable_weather_code(hour: Mapping[str, object]) -> bool:
    """Confirm the provider supplied a weather code this integration understands."""
    return str(hour.get("icon")) in CONDITION_MAP


def daily_rain_guidance(
    hourly: object,
    hourly_status: Mapping[str, object],
    now: datetime,
) -> dict[str, object]:
    """Return the only three allowed same-Shanghai-day rain states."""
    local_now = now.astimezone(SHANGHAI)
    end = local_now.replace(hour=23, minute=59, second=59, microsecond=999999)
    if not isinstance(hourly, list):
        return {"state": "unconfirmed", "window_end": end.isoformat()}
    first_hour = _first_remaining_hour(local_now)
    last_hour = end.replace(minute=0, second=0, microsecond=0)
    expected = _expected_hours(first_hour, last_hour)
    candidates: dict[datetime, Mapping[str, object]] = {}
    malformed_hour = False
    for item in hourly:
        if not isinstance(item, Mapping):
            malformed_hour = True
            continue
        timestamp = _as_datetime(item.get("datetime"))
        if timestamp is None:
            malformed_hour = True
            continue
        local_time = timestamp.astimezone(SHANGHAI)
        if local_time in expected:
            if local_time in candidates:
                malformed_hour = True
            candidates[local_time] = item
    if any(_has_rain_evidence(item) for item in candidates.values()):
        return {"state": "rain_expected", "window_end": end.isoformat()}
    if (
        hourly_status.get("state") == "fresh"
        and expected
        and set(candidates) == expected
        and not malformed_hour
        and all(_has_interpretable_weather_code(item) for item in candidates.values())
    ):
        return {"state": "no_rain_expected", "window_end": end.isoformat()}
    return {"state": "unconfirmed", "window_end": end.isoformat()}
