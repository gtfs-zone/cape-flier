import re
from datetime import date

import pytest
from conftest import fixture_files, fixture_zip, make_zip

from cape_flier.build import build_site
from cape_flier.config import Site

MONDAY = date(2026, 10, 5)


def build(name: str, **options) -> dict[str, str]:
    site = Site(slug="test", url="https://example.org/g.zip", **options)
    files = build_site(fixture_zip(name), site, today=MONDAY)
    return {path: body.decode() for path, body in files.items()}


def test_site_files():
    files = build("branching", title="Test & Co")
    assert set(files) == {"index.html", "4/index.html", "sitemap.xml", "style.css"}
    home = files["index.html"]
    assert "Test &amp; Co</h1>" in home
    assert 'href="4/">' in home
    assert '<link rel="canonical" href="https://sites.gtfs.zone/test/">' in home
    assert "<loc>https://sites.gtfs.zone/test/4/</loc>" in files["sitemap.xml"]


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
    assert set(files) == {"index.html", "4/index.html", "sitemap.xml", "style.css"}
    home = files["index.html"]
    assert '<link rel="stylesheet" href="style.css">' in home
    assert "--color-primary: #0E4C92; --color-primary-content: #FFFFFF;" in home
    page = files["4/index.html"]
    assert '<link rel="stylesheet" href="../style.css">' in page
    assert "<nav" not in page.split("<main", 1)[1]
    assert "<details" not in page
    assert '<section class="card bg-base-100 shadow-sm" id="' in page
    assert "picture" in page
    rows = re.findall(r'<th scope="row">.*?</th>', page, re.S)
    assert rows and all('<span class="dot"' in row for row in rows)
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


def test_arrival_and_departure_rows_on_dwells():
    files = fixture_files("branching")
    files["stop_times.txt"] = (
        files["stop_times.txt"]
        .replace("north1,08:10:00,08:10:00,B,2", "north1,08:10:00,08:15:00,B,2")
        .replace("north2,09:10:00,09:10:00,B,2", "north2,09:10:00,09:12:00,B,2")
    )
    site = Site(slug="test", url="https://example.org/g.zip")
    page = build_site(make_zip(files), site, today=MONDAY)["4/index.html"].decode()
    arrival = r'<tr class="ar"><th scope="row">.*?Bravo</a> <small>ar</small>'
    assert re.search(arrival, page)
    assert '<tr class="dp"><th scope="row"><small>dp</small></th>' in page
    assert "<td>8:10</td>" in page and "<td>8:15</td>" in page
    assert "ar: arrives, dp: departs." in page
