"""Privacy-preserving provider location helpers."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping, Protocol

from .const import (
    CONF_WARNING_CITY_ID,
    CONF_WARNING_CITY_NAME,
    CONF_WARNING_COUNTRY,
    CONF_WARNING_LOCATION_COORDINATES,
    CONF_WARNING_LOCATION_ID,
    CONF_WARNING_LOCATION_NAME,
)
from .household_warnings import WarningJurisdiction


COORDINATE_GRID_DEGREES = Decimal("0.05")
_CHINA_NAMES = {"china", "cn", "中国"}
_SHANGHAI_NAMES = {"shanghai", "上海", "上海市"}


class LocationLookupClient(Protocol):
    """Small portion of the QWeather client used for jurisdiction checks."""

    async def city_lookup(self, location: str, lang: str) -> dict[str, Any]:
        """Look up one provider location."""


class QuantizedLocationMismatch(ValueError):
    """Raised when a quantized point leaves the selected warning jurisdiction."""


def _quantize_coordinate(value: str | float) -> str:
    try:
        coordinate = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError("Invalid coordinate") from error
    grid_units = (coordinate / COORDINATE_GRID_DEGREES).quantize(
        Decimal("1"),
        rounding=ROUND_HALF_UP,
    )
    return f"{grid_units * COORDINATE_GRID_DEGREES:.2f}"


def quantize_coordinates(lon: str | float, lat: str | float) -> str:
    """Quantize longitude and latitude to an approximately five-kilometre grid."""
    return f"{_quantize_coordinate(lon)},{_quantize_coordinate(lat)}"


def quantize_location_input(location: str) -> str:
    """Quantize coordinate input before lookup and preserve city names or IDs."""
    parts = [part.strip() for part in location.split(",")]
    if len(parts) != 2:
        return location.strip()
    try:
        return quantize_coordinates(parts[0], parts[1])
    except ValueError:
        return location.strip()


def _warning_jurisdiction(location: dict[str, Any]) -> tuple[Any, Any, Any]:
    return location.get("country"), location.get("adm1"), location.get("adm2")


def _normalized_place_name(value: Any) -> str:
    return str(value or "").strip().casefold()


def _same_location_value(value: Any, expected: str) -> bool:
    return _normalized_place_name(value) == _normalized_place_name(expected)


def _required_location_value(location: Mapping[str, Any], field: str) -> str:
    value = location.get(field)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise QuantizedLocationMismatch(
        "Provider warning location is missing a required administrative field"
    )


def is_expected_shanghai_jurisdiction(location: dict[str, Any]) -> bool:
    """Return whether one provider location is the household Shanghai area."""
    country, adm1, adm2 = (
        _normalized_place_name(part) for part in _warning_jurisdiction(location)
    )
    return (
        country in _CHINA_NAMES
        and adm1 in _SHANGHAI_NAMES
        and adm2 in _SHANGHAI_NAMES
    )


def verified_shanghai_location(response: dict[str, Any]) -> dict[str, Any]:
    """Return the first verified Shanghai location or fail closed."""
    candidates = response.get("location", []) if response.get("code") == "200" else []
    try:
        return next(
            candidate
            for candidate in candidates
            if is_expected_shanghai_jurisdiction(candidate)
        )
    except StopIteration as error:
        raise QuantizedLocationMismatch(
            "Provider location is outside the expected Shanghai jurisdiction"
        ) from error


def city_candidate_for_district(
    candidates: list[dict[str, Any]], district: dict[str, Any]
) -> dict[str, Any]:
    """Return one structured parent-city candidate for a district selection."""
    district_city = _required_location_value(district, "adm2")
    district_country = _required_location_value(district, "country")
    district_province = _required_location_value(district, "adm1")
    matches = [
        candidate
        for candidate in candidates
        if _normalized_place_name(candidate.get("name"))
        == _normalized_place_name(district_city)
        and _normalized_place_name(candidate.get("country"))
        == _normalized_place_name(district_country)
        and _normalized_place_name(candidate.get("adm1"))
        == _normalized_place_name(district_province)
    ]
    if len(matches) != 1:
        raise QuantizedLocationMismatch(
            "Provider did not return one structured parent city for the district"
        )
    return matches[0]


def is_district_location_candidate(location: Mapping[str, Any]) -> bool:
    """Return whether structured lookup metadata describes a district, not its city."""
    try:
        name = _required_location_value(location, "name")
        city_name = _required_location_value(location, "adm2")
        _required_location_value(location, "country")
        _required_location_value(location, "adm1")
        _required_location_value(location, "id")
        _required_location_value(location, "lon")
        _required_location_value(location, "lat")
    except QuantizedLocationMismatch:
        return False
    return _normalized_place_name(name) != _normalized_place_name(city_name)


def warning_jurisdiction_config(
    district: dict[str, Any], city: dict[str, Any]
) -> dict[str, str]:
    """Keep only a chosen district's representative warning location in entry data."""
    if not is_district_location_candidate(district):
        raise QuantizedLocationMismatch("A warning jurisdiction must be district-level")
    district_name = _required_location_value(district, "name")
    city_name = _required_location_value(city, "name")
    if _normalized_place_name(district_name) == _normalized_place_name(city_name):
        raise QuantizedLocationMismatch("A warning jurisdiction must be district-level")
    return {
        CONF_WARNING_LOCATION_ID: _required_location_value(district, "id"),
        CONF_WARNING_LOCATION_NAME: district_name,
        CONF_WARNING_CITY_ID: _required_location_value(city, "id"),
        CONF_WARNING_CITY_NAME: city_name,
        CONF_WARNING_COUNTRY: _required_location_value(district, "country"),
        CONF_WARNING_LOCATION_COORDINATES: quantize_coordinates(
            _required_location_value(district, "lon"),
            _required_location_value(district, "lat"),
        ),
    }


def warning_jurisdiction_from_config(
    config_data: dict[str, Any],
) -> WarningJurisdiction | None:
    """Load the optional private warning jurisdiction without logging it."""
    configured_values = (
        CONF_WARNING_LOCATION_ID,
        CONF_WARNING_LOCATION_NAME,
        CONF_WARNING_CITY_ID,
        CONF_WARNING_CITY_NAME,
        CONF_WARNING_COUNTRY,
        CONF_WARNING_LOCATION_COORDINATES,
    )
    if not any(config_data.get(key) for key in configured_values):
        return None
    district_id = _required_location_value(config_data, CONF_WARNING_LOCATION_ID)
    district_name = _required_location_value(config_data, CONF_WARNING_LOCATION_NAME)
    city_id = _required_location_value(config_data, CONF_WARNING_CITY_ID)
    city_name = _required_location_value(config_data, CONF_WARNING_CITY_NAME)
    country = _required_location_value(config_data, CONF_WARNING_COUNTRY)
    coordinates = _required_location_value(
        config_data, CONF_WARNING_LOCATION_COORDINATES
    )
    parts = coordinates.split(",")
    if len(parts) != 2:
        raise QuantizedLocationMismatch("Warning jurisdiction has invalid coordinates")
    longitude, latitude = (part.strip() for part in parts)
    try:
        normalized_coordinates = quantize_coordinates(longitude, latitude)
    except ValueError as error:
        raise QuantizedLocationMismatch(
            "Warning jurisdiction has invalid coordinates"
        ) from error
    longitude, latitude = normalized_coordinates.split(",")
    return WarningJurisdiction(
        district_id=district_id,
        district_name=district_name,
        city_id=city_id,
        city_name=city_name,
        country=country,
        longitude=longitude,
        latitude=latitude,
    )


def warning_city_coordinates(
    response: Mapping[str, Any], jurisdiction: WarningJurisdiction
) -> tuple[str, str]:
    """Return the configured parent city's provider coordinate without persisting it."""
    candidates = response.get("location") if response.get("code") == "200" else []
    if not isinstance(candidates, list):
        raise QuantizedLocationMismatch("Provider warning city lookup failed")
    matches = [
        candidate
        for candidate in candidates
        if isinstance(candidate, Mapping)
        and _same_location_value(candidate.get("id"), jurisdiction.city_id)
        and _same_location_value(candidate.get("name"), jurisdiction.city_name)
        and _same_location_value(candidate.get("country"), jurisdiction.country)
    ]
    if len(matches) != 1:
        raise QuantizedLocationMismatch(
            "Provider did not return one configured warning city"
        )
    return (
        _required_location_value(matches[0], "lon"),
        _required_location_value(matches[0], "lat"),
    )


async def async_quantize_and_verify_location(
    client: LocationLookupClient,
    selected_location: dict[str, Any],
    *,
    language: str,
) -> str:
    """Quantize a point and fail closed if QWeather maps it elsewhere."""
    coordinates = quantize_coordinates(
        selected_location["lon"],
        selected_location["lat"],
    )
    response = await client.city_lookup(coordinates, lang=language)
    expected = _warning_jurisdiction(selected_location)
    candidates = response.get("location", []) if response.get("code") == "200" else []
    if (
        not is_expected_shanghai_jurisdiction(selected_location)
        or not any(
            _warning_jurisdiction(candidate) == expected
            and is_expected_shanghai_jurisdiction(candidate)
            for candidate in candidates
        )
    ):
        raise QuantizedLocationMismatch(
            "Quantized location does not match the selected warning jurisdiction"
        )
    return coordinates


async def async_quantize_and_verify_warning_jurisdiction(
    client: LocationLookupClient,
    district: Mapping[str, Any],
    *,
    language: str,
) -> str:
    """Quantize a selected district point and prove it remains in that district."""
    coordinates = quantize_coordinates(
        _required_location_value(district, "lon"),
        _required_location_value(district, "lat"),
    )
    response = await client.city_lookup(coordinates, lang=language)
    candidates = response.get("location", []) if response.get("code") == "200" else []
    district_id = _required_location_value(district, "id")
    country = _required_location_value(district, "country")
    province = _required_location_value(district, "adm1")
    city = _required_location_value(district, "adm2")
    if not any(
        _same_location_value(candidate.get("id"), district_id)
        and _same_location_value(candidate.get("country"), country)
        and _same_location_value(candidate.get("adm1"), province)
        and _same_location_value(candidate.get("adm2"), city)
        for candidate in candidates
        if isinstance(candidate, Mapping)
    ):
        raise QuantizedLocationMismatch(
            "Quantized location does not match the selected warning jurisdiction"
        )
    return coordinates
