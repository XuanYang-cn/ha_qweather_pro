"""Programmable provider clients for config-entry contract tests."""

from copy import deepcopy
from typing import Any


QWEATHER_RESPONSES = {
    "location": {
        "code": "200",
        "location": [
            {
                "id": "synthetic-shanghai",
                "name": "上海",
                "country": "中国",
                "adm1": "上海市",
                "adm2": "上海市",
                "lon": "121.45",
                "lat": "31.25",
            }
        ],
    },
    "now": {
        "code": "200",
        "now": {
            "temp": "24",
            "text": "多云",
            "icon": "101",
            "humidity": "63",
            "pressure": "1008",
            "windSpeed": "12",
            "wind360": "135",
            "windDir": "东南风",
            "windScale": "3",
            "feelsLike": "25",
            "obsTime": "2026-07-14T08:00+08:00",
        },
    },
    "daily": {
        "code": "200",
        "updateTime": "2026-07-14T08:00+08:00",
        "daily": [],
    },
    "hourly": {
        "code": "200",
        "updateTime": "2026-07-14T08:00+08:00",
        "hourly": [],
    },
    "warning": {"metadata": {"tag": "synthetic"}, "alerts": []},
    "air": {
        "metadata": {"tag": "synthetic"},
        "indexes": [
            {
                "aqi": 42,
                "pubTime": "2026-07-14T08:00+08:00",
                "category": "优",
                "level": "1",
                "primaryPollutant": None,
                "health": {},
            }
        ],
        "pollutants": [],
    },
    "indices": {"code": "200", "daily": []},
}


class FakeQWeatherClient:
    """Return configured QWeather payloads and record every endpoint call."""

    def __init__(self, responses: dict[str, dict[str, Any]] | None = None) -> None:
        self.responses = deepcopy(responses or QWEATHER_RESPONSES)
        self.calls: list[str] = []
        self.location_calls: list[tuple[str, str]] = []
        self.forecast_calls: list[str] = []
        self.hourly_calls: list[str] = []

    async def _response(self, name: str) -> dict[str, Any]:
        self.calls.append(name)
        response = self.responses[name]
        if isinstance(response, Exception):
            raise response
        return deepcopy(response)

    async def get_weather_now(self, *_args: Any) -> dict[str, Any]:
        return await self._response("now")

    async def city_lookup(self, location: str, lang: str) -> dict[str, Any]:
        self.calls.append("location")
        self.location_calls.append((location, lang))
        return deepcopy(self.responses["location"])

    async def get_forecast(self, _lat: str, _lon: str, days: str, _lang: str) -> dict[str, Any]:
        self.forecast_calls.append(days)
        return await self._response("daily")

    async def get_hourly(self, _lat: str, _lon: str, hours: str, _lang: str) -> dict[str, Any]:
        self.hourly_calls.append(hours)
        return await self._response("hourly")

    async def get_warning_v1(self, *_args: Any) -> dict[str, Any]:
        return await self._response("warning")

    async def get_air_v1(self, *_args: Any) -> dict[str, Any]:
        return await self._response("air")

    async def get_indices(self, *_args: Any) -> dict[str, Any]:
        return await self._response("indices")

    async def get_grid_weather_now(self, *_args: Any) -> dict[str, Any]:
        raise AssertionError("The first fork version must not call grid weather")

    async def get_grid_forecast(self, *_args: Any) -> dict[str, Any]:
        raise AssertionError("The first fork version must not call grid forecasts")

    async def get_grid_hourly(self, *_args: Any) -> dict[str, Any]:
        raise AssertionError("The first fork version must not call grid forecasts")

    async def get_minutely(self, *_args: Any) -> dict[str, Any]:
        raise AssertionError("The first fork version must not call minutely weather")


class FakeNationwideWarningClient:
    """Return one programmable nationwide-warning snapshot."""

    def __init__(self, response: dict[str, Any]) -> None:
        self.response = deepcopy(response)
        self.calls = 0

    async def async_fetch_active_warnings(self) -> dict[str, Any]:
        self.calls += 1
        return deepcopy(self.response)
