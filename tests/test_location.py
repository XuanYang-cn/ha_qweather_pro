"""Privacy-safe location contract tests."""

import pytest

from custom_components.qweather_pro.location import (
    QuantizedLocationMismatch,
    async_quantize_and_verify_location,
    async_quantize_and_verify_warning_jurisdiction,
    city_candidate_for_district,
    is_district_location_candidate,
    quantize_coordinates,
    quantize_location_input,
    warning_city_coordinates,
    warning_jurisdiction_from_config,
    warning_jurisdiction_config,
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


def test_coordinate_input_is_quantized_before_lookup_but_city_names_are_preserved() -> None:
    assert quantize_location_input("121.4737, 31.2304") == "121.45,31.25"
    assert quantize_location_input("上海市") == "上海市"


async def test_non_shanghai_location_fails_even_when_quantized_jurisdiction_matches() -> None:
    suzhou = {
        **SYNTHETIC_SHANGHAI,
        "name": "苏州",
        "adm1": "江苏省",
        "adm2": "苏州市",
    }
    client = FakeLookupClient([suzhou])

    with pytest.raises(QuantizedLocationMismatch):
        await async_quantize_and_verify_location(
            client,
            suzhou,
            language="zh",
        )


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


async def test_warning_district_quantization_requires_the_same_district_id() -> None:
    district = {
        "id": "synthetic-district",
        "name": "Synthetic District",
        "adm1": "Synthetic Province",
        "adm2": "Synthetic City",
        "country": "Synthetic Country",
        "lon": "120.004",
        "lat": "30.004",
    }
    verified = {**district, "lon": "120.00", "lat": "30.00"}
    client = FakeLookupClient([verified])

    coordinates = await async_quantize_and_verify_warning_jurisdiction(
        client,
        district,
        language="zh",
    )

    assert coordinates == "120.00,30.00"
    assert client.calls == [("120.00,30.00", "zh")]

    with pytest.raises(QuantizedLocationMismatch):
        await async_quantize_and_verify_warning_jurisdiction(
            FakeLookupClient([{**verified, "id": "other-district"}]),
            district,
            language="zh",
        )


def test_warning_jurisdiction_uses_only_selected_district_representative_data() -> None:
    district = {
        "id": "synthetic-district",
        "name": "Synthetic District",
        "adm1": "Synthetic Province",
        "adm2": "Synthetic City",
        "country": "Synthetic Country",
        "lon": "120.004",
        "lat": "30.004",
    }
    city = {
        "id": "synthetic-city",
        "name": "Synthetic City",
        "adm1": "Synthetic Province",
        "adm2": "Synthetic City",
        "country": "Synthetic Country",
        "lon": "120.00",
        "lat": "30.00",
    }

    config = warning_jurisdiction_config(district, city)

    assert config == {
        "warning_location_id": "synthetic-district",
        "warning_location_name": "Synthetic District",
        "warning_city_id": "synthetic-city",
        "warning_city_name": "Synthetic City",
        "warning_country": "Synthetic Country",
        "warning_location_coordinates": "120.00,30.00",
    }


def test_city_candidate_requires_one_structured_parent_city() -> None:
    district = {
        "id": "synthetic-district",
        "name": "Synthetic District",
        "adm1": "Synthetic Province",
        "adm2": "Synthetic City",
        "country": "Synthetic Country",
        "lon": "120.00",
        "lat": "30.00",
    }
    city = {
        "id": "synthetic-city",
        "name": "Synthetic City",
        "adm1": "Synthetic Province",
        "adm2": "Synthetic City",
        "country": "Synthetic Country",
        "lon": "120.00",
        "lat": "30.00",
    }

    assert city_candidate_for_district([city], district) == city
    with pytest.raises(QuantizedLocationMismatch):
        city_candidate_for_district([], district)
    with pytest.raises(QuantizedLocationMismatch):
        city_candidate_for_district([city, city], district)


def test_warning_location_search_hides_city_level_candidates() -> None:
    district = {
        "id": "synthetic-district",
        "name": "Synthetic District",
        "adm1": "Synthetic Province",
        "adm2": "Synthetic City",
        "country": "Synthetic Country",
        "lon": "120.00",
        "lat": "30.00",
    }
    city = {**district, "id": "synthetic-city", "name": "Synthetic City"}

    assert is_district_location_candidate(district)
    assert not is_district_location_candidate(city)
    assert not is_district_location_candidate({"id": "incomplete"})


def test_warning_jurisdiction_requires_a_complete_private_config_entry_value() -> None:
    config = {
        "warning_location_id": "synthetic-district",
        "warning_location_name": "Synthetic District",
        "warning_city_id": "synthetic-city",
        "warning_city_name": "Synthetic City",
        "warning_country": "Synthetic Country",
        "warning_location_coordinates": "120.00,30.00",
    }

    jurisdiction = warning_jurisdiction_from_config(config)

    assert jurisdiction is not None
    assert jurisdiction.label == "Synthetic District · Synthetic City · Synthetic Country"
    assert (jurisdiction.longitude, jurisdiction.latitude) == ("120.00", "30.00")
    assert warning_jurisdiction_from_config({}) is None
    with pytest.raises(QuantizedLocationMismatch):
        warning_jurisdiction_from_config({**config, "warning_city_id": ""})


def test_warning_city_coordinates_requires_the_configured_parent_city() -> None:
    jurisdiction = warning_jurisdiction_from_config(
        {
            "warning_location_id": "synthetic-district",
            "warning_location_name": "Synthetic District",
            "warning_city_id": "synthetic-city",
            "warning_city_name": "Synthetic City",
            "warning_country": "Synthetic Country",
            "warning_location_coordinates": "120.00,30.00",
        }
    )
    assert jurisdiction is not None
    response = {
        "code": "200",
        "location": [
            {
                "id": "synthetic-city",
                "name": "Synthetic City",
                "country": "Synthetic Country",
                "lon": "120.00",
                "lat": "30.00",
            }
        ],
    }

    assert warning_city_coordinates(response, jurisdiction) == ("120.00", "30.00")
    with pytest.raises(QuantizedLocationMismatch):
        warning_city_coordinates(
            {"code": "200", "location": [{**response["location"][0], "id": "other"}]},
            jurisdiction,
        )
