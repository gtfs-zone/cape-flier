from pathlib import Path

import pytest
from pydantic import ValidationError

from cape_flier.config import BasemapPair, RouteFilter, load_config

REPO_CONFIG = Path(__file__).parent.parent / "sites.yaml"


def test_repo_config_loads():
    config = load_config(REPO_CONFIG.read_text())
    assert config.site("columbia-county").basemap == "stadia-toner-dark"
    assert config.site("amtrak").brand_color == "00537E"


def test_site_overrides_defaults():
    config = load_config(
        """
defaults: {time_format: 24h, horizon_days: 14}
sites:
  - {slug: a, url: "https://example.org/a.zip"}
  - {slug: b, url: "https://example.org/b.zip", time_format: 12h}
"""
    )
    assert config.site("a").time_format == "24h"
    assert config.site("a").horizon_days == 14
    assert config.site("b").time_format == "12h"


def test_basemap_pair():
    config = load_config(
        "sites: [{slug: a, url: u, basemap:"
        " {light: stadia-toner-lite, dark: stadia-toner-dark}}]"
    )
    assert config.site("a").basemap == BasemapPair(
        light="stadia-toner-lite", dark="stadia-toner-dark"
    )


@pytest.mark.parametrize(
    "text",
    [
        "defaults: {colour: red}",
        "sites: [{slug: a, url: u, colour: red}]",
        "sites: [{slug: a}]",
        "sites: [{slug: a, url: u, feed: f-0123456789}]",
        "sites: [{slug: Bad Slug, url: u}]",
        "sites: [{slug: a, url: u}, {slug: a, url: v}]",
        "sites: [{slug: a, url: u, style: fancy}]",
        "sites: [{slug: a, url: u, orientation: trips-down}]",
        "sites: [{slug: a, url: u, brand_color: red}]",
        "sites: [{slug: a, url: u, basemap: osm}]",
        "sites: [{slug: a, url: u, basemap: {light: stadia-toner-lite}}]",
        "sites: [{slug: a, url: u, interactive_map: true}]",
    ],
)
def test_invalid_config(text):
    with pytest.raises(ValidationError):
        load_config(text)


def test_download_url_from_feeds_doc():
    site = load_config("sites: [{slug: a, feed: f-0123456789}]").site("a")
    doc = {
        "feeds": [
            {"feedId": "f-0123456789", "urls": {"scheduled": ["https://x/g.zip"]}}
        ]
    }
    assert site.download_url(doc) == "https://x/g.zip"
    with pytest.raises(LookupError):
        site.download_url({"feeds": []})


def test_route_filter():
    rail = RouteFilter(route_types=(2,), exclude_route_ids=("CR-Foxboro",))
    assert rail.accepts("CR-Fitchburg", 2)
    assert not rail.accepts("Red", 1)
    assert not rail.accepts("CR-Foxboro", 2)
    assert RouteFilter().accepts("anything", 3)
