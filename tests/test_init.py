"""Baseline identity tests for the personal fork."""

import json
from pathlib import Path

from custom_components.qweather_pro.const import DOMAIN


def test_domain_and_fork_version_remain_compatible() -> None:
    """Keep the upstream domain while making the fork version recognizable."""
    manifest = json.loads(
        Path("custom_components/qweather_pro/manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert DOMAIN == "qweather_pro"
    assert manifest["domain"] == DOMAIN
    assert manifest["version"].startswith("1.1.6-yx.")
