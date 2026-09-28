import json
import re
from datetime import date

import pytest
from conftest import fixture_files, fixture_zip, make_zip

from cape_flier.build import build_root, build_site, page_digest
from cape_flier.catalog import shard_of
from cape_flier.config import CatalogFeed, Site

MONDAY = date(2026, 10, 5)


def build(name: str, **options) -> dict[str, str]:
    site = Site(slug="test", url="https://example.org/g.zip", **options)
    files = build_site(fixture_zip(name), site, today=MONDAY)
    return {path: body.decode() for path, body in files.items()}


def test_site_files():
    files = build("branching", title="Test & Co")
    assert set(files) == {
        "index.html",
        "4/index.html",
        "site.json",
        "style.css",
        "logo.svg",
    }
    home = files["index.html"]
    assert "Test &amp; Co</h1>" in home
    assert 'href="4/">' in home
    assert '<link rel="canonical" href="https://sites.gtfs.zone/test/">' in home


def test_route_page_has_timetable():
    page = build("overnight")["1/index.html"]
    assert '<section class="card bg-base-100 shadow-sm" id="daily">' in page
    assert "Charlie</a> <small>CDT time</small></th>" in page
    assert '<td class="pm">11:40</td>' in page
    assert "PM times are in bold." in page


def test_24h_times_not_bold():
    page = build("overnight", time_format="24h")["1/index.html"]
    assert "<td>23:40</td>" in page
    assert 'class="pm"' not in page


def test_multiday_markers_and_legend():
    page = build("multiday")["1/index.html"]
    assert "11:30<sup>+1</sup>" in page
    assert "2:10<sup>+2</sup>" in page
    assert "+n: after midnight, n days later." in page


def test_frequency_column_footer():
    page = build("frequencies")["3/index.html"]
    assert "then every" in page


def test_not_a_zip():
    site = Site(slug="test", url="https://example.org/g.zip")
    with pytest.raises(Exception, match="zip"):
        build_site(b"not a zip", site)


def test_site_with_brand_and_basemap():
    files = build(
        "branching",
        basemap="stadia-toner",
        brand_color="0E4C92",
    )
    assert set(files) == {
        "index.html",
        "4/index.html",
        "site.json",
        "style.css",
        "logo.svg",
    }
    home = files["index.html"]
    assert '<link rel="stylesheet" href="style.css">' in home
    assert "--color-primary: #0E4C92; --color-primary-content: #FFFFFF;" in home
    page = files["4/index.html"]
    assert '<link rel="stylesheet" href="../style.css">' in page
    assert "<nav" not in page.split("<main", 1)[1]
    assert "<details" not in page
    assert '<section class="card bg-base-100 shadow-sm" id="' in page
    assert "stamen_toner/" in page
    assert '<link rel="icon" type="image/svg+xml" href="../logo.svg">' in page
    assert 'href="../../" aria-label="sites.gtfs.zone"' in page
    assert '<a href="4/" aria-label="4 Forks" data-cap="4 Forks">' in home
    rows = re.findall(r'<th scope="row">.*?</th>', page, re.S)
    assert rows and all('<span class="dot' in row for row in rows)
    assert all(
        'href="https://www.google.com/maps/search/?api=1&amp;query=' in row
        for row in rows
    )


def test_only_external_links_open_in_new_tab():
    for body in build("branching").values():
        for tag in re.findall(r"<a [^>]*>", body):
            href = re.search(r'href="([^"]*)"', tag)[1]
            assert not href.startswith("https://sites.gtfs.zone"), tag
            assert ('target="_blank"' in tag) == href.startswith("http"), tag


def test_same_headsign_runs_share_a_header_cell():
    files = fixture_files("branching")
    files["trips.txt"] = files["trips.txt"].replace(
        "back_skip,Alpha", "back_skip,Charlie"
    )
    site = Site(slug="test", url="https://example.org/g.zip")
    page = build_site(make_zip(files), site, today=MONDAY)["4/index.html"].decode()
    row = re.search(r'<tr class="to">.*?</tr>', page)[0]
    assert '<th scope="col">Alpha</th><th scope="col" colspan="2">Charlie</th>' in row


def test_arrival_and_departure_share_a_cell_on_dwells():
    files = fixture_files("branching")
    files["stop_times.txt"] = (
        files["stop_times.txt"]
        .replace("north1,08:10:00,08:10:00,B,2", "north1,08:10:00,08:15:00,B,2")
        .replace("north2,09:10:00,09:10:00,B,2", "north2,09:10:00,09:12:00,B,2")
    )
    site = Site(slug="test", url="https://example.org/g.zip")
    page = build_site(make_zip(files), site, today=MONDAY)["4/index.html"].decode()
    assert 'class="ar"' not in page and 'class="dp"' not in page
    assert '<td class="dw"><span>8:10</span>8:15</td>' in page
    assert "Two times: arrives, then departs." in page


def test_rail_branches():
    page = build("branching")["4/index.html"]
    # Alpha-bound trips split at Delta: via Charlie or via Echo.
    delta = re.search(r'<th scope="row">.*?Delta</a>', page)[0]
    assert "C20,80 34,70 34,100" in delta
    echo = re.search(r'<th scope="row">[^\n]*?Echo</a>[^\n]*?</th>', page)[0]
    charlie = re.search(r'<th scope="row">[^\n]*?Charlie</a>[^\n]*?</th>', page)[0]
    assert 'style="left:20px"' in echo and "<small>" not in echo
    assert 'style="left:34px"' in charlie
    # Straight single-lane rows are drawn by CSS, with no SVG.
    assert '<span class="rail d" aria-hidden="true"><span class="dot solid"' in page


def test_site_json():
    summary = json.loads(build("branching", title="Test & Co")["site.json"])
    assert summary == {
        "slug": "test",
        "title": "Test & Co",
        "routes": 1,
        "brand_color": None,
        "valid_through": summary["valid_through"],
        "generated": "2026-10-05",
        "country_code": None,
        "country": None,
        "subdivision": None,
    }


def test_site_json_country_from_catalog():
    feed = CatalogFeed(
        feedId="f-0123456789",
        name="Test",
        country="United States",
        country_code="US",
        subdivision="Oregon",
    )
    site = Site(slug="test", feed=feed.feed_id, catalog=feed)
    summary = json.loads(
        build_site(fixture_zip("branching"), site, MONDAY)["site.json"]
    )
    assert summary["country_code"] == "US"
    assert summary["country"] == "United States"
    assert summary["subdivision"] == "Oregon"


def test_build_root():
    us = {"country_code": "US", "country": "United States"}
    summaries = [
        {"slug": "b", "title": "bravo", "routes": 1, "valid_through": None}
        | us
        | {"subdivision": "Oregon"},
        {
            "slug": "a",
            "title": "Alpha",
            "routes": 2,
            "brand_color": "80276C",
            "valid_through": "2026-12-01",
            "subdivision": "Maine",
        }
        | us,
        {"slug": "c", "title": "Charlie", "routes": 3},
        {"slug": "d", "title": "Delta", "routes": 1, "country_code": "CA"},
    ]
    pages = {"a": {"index.html": "2026-09-01", "r/index.html": "2026-10-05"}}
    files = {
        k: v.decode() for k, v in build_root(summaries, MONDAY, pages, "k3y").items()
    }
    shard = f"sitemaps/{shard_of('a'):02d}.xml"
    assert set(files) == {
        "index.html",
        "countries/us/index.html",
        "countries/ca/index.html",
        "countries/other/index.html",
        "error.html",
        "style.css",
        "logo.svg",
        "sitemap.xml",
        "sitemaps/root.xml",
        shard,
        "robots.txt",
        "k3y.txt",
    }
    home = files["index.html"]
    # By name, Other last.
    assert (
        home.index('href="countries/ca/"')
        < home.index('href="countries/us/"')
        < home.index('href="countries/other/"')
    )
    assert "United States</span>" in home and "2 agencies" in home
    assert re.search(r"\.gtfs\.zone<sup[^>]*>v\d+\.\d+\.\d+</sup>", home)
    assert 'href="https://gtfs.zone" target="_blank"' in home
    assert 'cape-flier" target="_blank" rel="noopener">cape-flier</a>' in home
    assert '"@type": "WebSite"' in home

    country = files["countries/us/index.html"]
    assert country.index(">Maine</h2>") < country.index(">Oregon</h2>")
    assert country.index('href="../../a/"') < country.index('href="../../b/"')
    assert "2 routes, to Dec 1" in country
    assert country.count('style="background:#80276C"') == 1
    assert '<link rel="stylesheet" href="../../style.css">' in country
    assert (
        '<link rel="canonical" href="https://sites.gtfs.zone/countries/us/">' in country
    )
    assert "<h2" not in files["countries/other/index.html"]

    index = files["sitemap.xml"]
    assert "<sitemapindex" in index
    assert "<loc>https://sites.gtfs.zone/sitemaps/root.xml</loc></sitemap>" in index
    assert (
        f"<loc>https://sites.gtfs.zone/{shard}</loc><lastmod>2026-10-05</lastmod>"
        in index
    )
    root_map = files["sitemaps/root.xml"]
    assert "<url><loc>https://sites.gtfs.zone/</loc></url>" in root_map
    assert "<loc>https://sites.gtfs.zone/countries/us/</loc>" in root_map
    sitemap = files[shard]
    assert (
        "<loc>https://sites.gtfs.zone/a/</loc><lastmod>2026-09-01</lastmod>" in sitemap
    )
    assert (
        "<loc>https://sites.gtfs.zone/a/r/</loc><lastmod>2026-10-05</lastmod>"
        in sitemap
    )
    assert files["k3y.txt"] == "k3y"
    assert '<link rel="stylesheet" href="/style.css">' in files["error.html"]
    assert '<meta name="robots" content="noindex">' in files["error.html"]
    assert "Sitemap: https://sites.gtfs.zone/sitemap.xml" in files["robots.txt"]
    assert summaries[1]["valid_through"] == "2026-12-01"


def json_ld(page: str) -> dict:
    match = re.search(r'<script type="application/ld\+json">(.*?)</script>', page)
    assert match
    return json.loads(match.group(1))


def test_route_page_seo():
    files = build("overnight", title="Test & Co")
    page = files["1/index.html"]
    assert "<title>1 Night Owl bus schedule - Test &amp; Co</title>" in page
    assert (
        '<meta name="description" content="1 Night Owl bus schedule between Alpha'
        " and Charlie: Daily. Times at each stop and first and last trips, from"
        ' Test &amp; Co.">'
    ) in page
    assert '<meta property="og:title" content="1 Night Owl bus schedule' in page
    assert '<meta property="og:url" content="https://sites.gtfs.zone/test/1/">' in page
    assert (
        "The 1 Night Owl bus route runs between Alpha and Charlie, with Daily"
        " timetables.</p>"
    ) in page
    assert "First trip starts at 6:00 AM, last at 11:40 PM.</p>" in page
    crumbs = json_ld(page)["itemListElement"]
    assert [c["item"] for c in crumbs] == [
        "https://sites.gtfs.zone/",
        "https://sites.gtfs.zone/test/",
        "https://sites.gtfs.zone/test/1/",
    ]
    assert crumbs[1]["name"] == "Test & Co"
    home = files["index.html"]
    assert "<title>Test &amp; Co schedules and timetables</title>" in home
    assert 'content="Bus schedules for Test &amp; Co: timetables for 1 route,' in home
    assert len(json_ld(home)["itemListElement"]) == 2


def test_page_digest_ignores_build_date():
    site = Site(slug="test", url="https://example.org/g.zip")
    body = fixture_zip("overnight")
    monday = build_site(body, site, today=MONDAY)["1/index.html"]
    tuesday = build_site(body, site, today=date(2026, 10, 6))["1/index.html"]
    assert monday != tuesday
    assert page_digest(monday) == page_digest(tuesday)
    assert page_digest(monday) != page_digest(monday.replace(b"11:40", b"11:45"))


def test_amenity_icons_and_feed_notes():
    files = build("amenities")
    page = files["7/index.html"]
    assert page.count('<symbol id="i-bike"') == 1
    assert 'aria-label="Bikes allowed"><use href="#i-bike"/>' in page
    assert "f</sup>" in page
    assert "<li>f: flag stop, stops only on request.</li>" in page
    # Every trip in the feed is accessible: said once, not marked per trip.
    for path in ("index.html", "7/index.html"):
        assert "All trips are wheelchair accessible.</p>" in files[path]
    assert "Wheelchair accessible trip." not in page
    assert "Filled dot" not in page


def test_no_icons_without_amenity_data():
    page = build("branching")["4/index.html"]
    assert "<symbol" not in page
    assert "amenities" not in page
