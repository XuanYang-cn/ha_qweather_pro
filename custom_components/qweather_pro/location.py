"""Privacy-preserving provider location helpers."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Protocol


COORDINATE_GRID_DEGREES = Decimal("0.05")


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
    if not any(_warning_jurisdiction(candidate) == expected for candidate in candidates):
        raise QuantizedLocationMismatch(
            "Quantized location does not match the selected warning jurisdiction"
        )
    return coordinates
