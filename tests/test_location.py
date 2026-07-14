"""Privacy-safe location contract tests."""

import pytest

from custom_components.qweather_pro.location import (
    QuantizedLocationMismatch,
    async_quantize_and_verify_location,
    quantize_coordinates,
)


SYNTHETIC_SHANGHAI = {
    "id": "synthetic-shanghai",
    "name": "上海",
    "country": "中国",
    "adm1": "上海市",
    "adm2": "上海市",
    "lon": "121.4737",
    "lat": "31.2304",
}


class FakeLookupClient:
    def __init__(self, locations: list[dict]) -> None:
        self.locations = locations
        self.calls: list[tuple[str, str]] = []

    async def city_lookup(self, location: str, lang: str) -> dict:
        self.calls.append((location, lang))
        return {"code": "200", "location": self.locations}


def test_coordinates_are_quantized_to_an_approximately_five_kilometre_grid() -> None:
    assert quantize_coordinates("121.4737", "31.2304") == "121.45,31.25"


async def test_quantized_point_must_remain_in_the_same_warning_jurisdiction() -> None:
    verified = {
        **SYNTHETIC_SHANGHAI,
        "id": "synthetic-quantized-shanghai",
        "lon": "121.45",
        "lat": "31.25",
    }
    client = FakeLookupClient([verified])

    coordinates = await async_quantize_and_verify_location(
        client,
        SYNTHETIC_SHANGHAI,
        language="zh",
    )

    assert coordinates == "121.45,31.25"
    assert client.calls == [("121.45,31.25", "zh")]


async def test_quantized_point_fails_closed_outside_the_original_jurisdiction() -> None:
    client = FakeLookupClient(
        [
            {
                **SYNTHETIC_SHANGHAI,
                "adm1": "江苏省",
                "adm2": "苏州市",
            }
        ]
    )

    with pytest.raises(QuantizedLocationMismatch):
        await async_quantize_and_verify_location(
            client,
            SYNTHETIC_SHANGHAI,
            language="zh",
        )
