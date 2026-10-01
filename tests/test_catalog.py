from pathlib import Path

import pytest

from gtfs_zone_timetable_sites.catalog import (
    SHARDS,
    assign_slugs,
    base_slug,
    resolve_sites,
    shard_of,
    slugify,
)
from gtfs_zone_timetable_sites.config import CatalogFeed, RouteFilter, load_config

REPO_CONFIG = Path(__file__).parent.parent / "sites.yaml"


def feed(feed_id, name="Bus", **fields):
    return {
        "feedId": feed_id,
        "name": name,
        "urls": {"scheduled": [f"https://x/{feed_id}.zip"]},
        "roleState": {"scheduled": "up"},
        "country_code": "US",
        "staticBytes": 1000,
    } | fields


def catalog_feed(feed_id, name):
    return CatalogFeed(feedId=feed_id, name=name)


def test_slugify():
    assert slugify("L'Inter des Laurentides") == "l-inter-des-laurentides"
    assert slugify("Société de transport") == "societe-de-transport"
    assert slugify("中津市") == "feed"
    assert base_slug(catalog_feed("f-0000000001", "中津市")) == "f-0000000001"
    assert base_slug(catalog_feed("f-0000000002", "Countries")) == "f-0000000002"


def test_assign_slugs_pins_and_suffixes():
    feeds = [
        catalog_feed("f-0000000003", "Metro"),
        catalog_feed("f-0000000001", "Metro"),
        catalog_feed("f-0000000002", "Metro Transit"),
    ]
    slugs = assign_slugs(feeds, {"f-0000000002": "mt"}, {"metro"})
    # Pinned kept; new ones by feed id, past slugs already taken.
    assert slugs == {
        "f-0000000001": "metro-2",
        "f-0000000002": "mt",
        "f-0000000003": "metro-3",
    }


def test_assign_slugs_never_reuses_a_dropped_feeds_slug():
    slugs = assign_slugs(
        [catalog_feed("f-0000000002", "Metro")], {"f-0000000001": "metro"}, set()
    )
    assert slugs["f-0000000002"] == "metro-2"
    assert slugs["f-0000000001"] == "metro"


def test_resolve_sites_filters_and_overrides():
    config = load_config(
        """
defaults: {time_format: 24h}
catalog: {countries: [US, CA], max_bytes: 5000, exclude: [f-000000000e]}
sites:
  - {feed: f-0000000001, title: Listed, time_format: 12h}
  - {slug: manual, feed: f-0000000002}
  - {slug: direct, url: "https://y/z.zip"}
  - {feed: f-00000000ff}
"""
    )
    doc = {
        "feeds": [
            feed("f-0000000001", "One", country_code="FR"),
            feed("f-0000000002", "Two"),
            feed("f-0000000003", "Three"),
            feed("f-0000000004", "Four", country_code="CA", staticBytes=None),
            feed("f-0000000005", "Too Big", staticBytes=6000),
            feed("f-0000000006", "Elsewhere", country_code="JP"),
            feed("f-0000000007", "Down", roleState={"scheduled": "down"}),
            feed("f-0000000008", "No schedule", urls={"vehicles": ["v"]}),
            feed("f-000000000e", "Excluded"),
        ]
    }
    sites, slugs = resolve_sites(config, doc, {"f-0000000003": "three-pinned"})
    by_slug = {site.slug: site for site in sites}
    assert list(by_slug) == [
        "one",
        "manual",
        "direct",
        "f-00000000ff",
        "three-pinned",
        "four",
    ]
    # Listed feeds skip the filter and keep their options.
    assert by_slug["one"].title == "Listed"
    assert by_slug["one"].time_format == "12h"
    assert by_slug["one"].catalog.country_code == "FR"
    assert by_slug["manual"].catalog.name == "Two"
    assert by_slug["direct"].catalog is None
    # Not in feeds.json: listed without a catalog entry, fails on download.
    assert by_slug["f-00000000ff"].catalog is None
    assert by_slug["four"].time_format == "24h"
    assert by_slug["four"].download_url() == "https://x/f-0000000004.zip"
    assert slugs == {
        "f-0000000001": "one",
        "f-0000000003": "three-pinned",
        "f-0000000004": "four",
        "f-00000000ff": "f-00000000ff",
    }


def test_resolve_sites_without_catalog_takes_only_listed():
    config = load_config("sites: [{slug: a, url: u}]")
    sites, slugs = resolve_sites(config, {"feeds": [feed("f-0000000001")]}, {})
    assert [site.slug for site in sites] == ["a"]
    assert slugs == {}


def test_resolve_sites_rejects_a_slug_taken_twice():
    config = load_config("catalog: {}\nsites: [{slug: bus, feed: f-0000000001}]")
    doc = {"feeds": [feed("f-0000000001"), feed("f-0000000002")]}
    with pytest.raises(ValueError, match="bus"):
        resolve_sites(config, doc, {"f-0000000002": "bus"})


def test_shard_of_is_stable_and_spread():
    assert shard_of("amtrak") == shard_of("amtrak")
    shards = {shard_of(f"site-{n}") for n in range(500)}
    assert shards == set(range(SHARDS))


def test_repo_config_takes_whole_feeds_from_the_catalog():
    config = load_config(REPO_CONFIG.read_text())
    doc = {
        "feeds": [
            feed("f-1f748c5476", "MBTA"),
            feed("f-2f033a022e", "Amtrak"),
            feed("f-ff2cfa2434", "Columbia County", country_code=None),
        ]
    }
    sites, _ = resolve_sites(config, doc, {})
    by_slug = {site.slug: site for site in sites}
    # No country code, so the catalog filter skips it.
    assert set(by_slug) == {"mbta", "amtrak"}
    assert all(site.routes == RouteFilter() for site in sites)


def test_repo_config_dev_feeds_are_valid():
    config = load_config(REPO_CONFIG.read_text())
    assert config.dev and len(set(config.dev)) == len(config.dev)
