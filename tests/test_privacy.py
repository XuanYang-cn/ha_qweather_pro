"""Credential and private-host logging tests."""

import logging

from custom_components.qweather_pro.api import QWeatherAPI


class FakeErrorResponse:
    status = 403

    async def json(self) -> dict:
        return {"error": {"title": "Synthetic denial"}}


class FakeSession:
    async def get(self, *_args, **_kwargs) -> FakeErrorResponse:
        return FakeErrorResponse()


async def test_personal_api_host_is_not_written_to_logs(caplog) -> None:
    private_host = "account-specific-host.example.invalid"
    client = QWeatherAPI(
        session=FakeSession(),
        host=private_host,
    )

    with caplog.at_level(logging.ERROR):
        response = await client.request("v7", "weather/now", {})

    assert response["code"] == "403"
    assert private_host not in caplog.text
