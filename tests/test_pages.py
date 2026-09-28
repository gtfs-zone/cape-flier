from datetime import date

from conftest import fixture_zip, make_zip

from cape_flier.build import site_feed, site_timetables
from cape_flier.config import Site
from cape_flier.gtfs.reader import Route, read_feed
from cape_flier.pages import (
    ColumnHead,
    HeadsignSpan,
    badge_colors,
    brand_colors,
    clock,
    day_views,
    google_link,
    headsign_spans,
    route_labels,
    route_slugs,
    slugify,
    table_title,
)


def route(route_id="r", short="", long="", color=None, text=None) -> Route:
    return Route(
        route_id=route_id,
        agency_id="",
        short_name=short,
        long_name=long,
        desc="",
        route_type=3,
        color=color,
        text_color=text,
        sort_order=None,
        url="",
    )


def test_clock_12h_marks_pm_and_next_day():
    assert clock(9 * 3600, "12h").text == "9:00"
    assert not clock(9 * 3600, "12h").pm
    assert clock(12 * 3600 + 5 * 60, "12h").text == "12:05"
    assert clock(12 * 3600, "12h").pm
    late = clock(24 * 3600 + 10 * 60, "12h")
    assert (late.text, late.pm, late.next_day) == ("12:10", False, True)


def test_clock_24h():
    shown = clock(25 * 3600 + 30 * 60, "24h")
    assert (shown.text, shown.pm, shown.next_day) == ("01:30", False, True)


def test_badge_text_falls_back_to_contrasting_color():
    assert badge_colors(route(color="FFFF00", text="FFFFFF")) == ("FFFF00", "000000")
    assert badge_colors(route(color="002599")) == ("002599", "FFFFFF")
    assert badge_colors(route(color="002599", text="FFCC00")) == ("002599", "FFCC00")
    assert badge_colors(route()) is None


def test_route_slugs_are_unique():
    routes = [route("a", long="Hudson <> Albany"), route("b", long="Hudson Albany")]
    assert route_slugs(routes, {}) == {"a": "hudson-albany", "b": "hudson-albany-2"}
    assert slugify("  Copake ") == "copake"


def test_headsign_spans_merge_adjacent_runs():
    heads = tuple(
        ColumnHead(number="", headsign=h, every="", shaded=shaded)
        for h, shaded in [
            ("A", True),
            ("A", True),
            ("B", False),
            ("A", True),
            ("A", False),
        ]
    )
    assert headsign_spans(heads) == (
        HeadsignSpan("A", 2, True),
        HeadsignSpan("B", 1, False),
        HeadsignSpan("A", 2, False),
    )


def test_table_title_skips_to_for_services_and_loops():
    assert table_title(["Albany", "Hudson"]) == "To Albany / Hudson"
    assert table_title(["Patriots Game Train"]) == "Patriots Game Train"
    assert table_title(["↷ 41 Clockwise"]) == "↷ 41 Clockwise"


def test_route_labels_name_agencies_of_shared_route_names():
    feed = read_feed(
        make_zip(
            {
                "agency.txt": "agency_id,agency_name,agency_url,agency_timezone\n"
                "a,Amtrak,https://example.org,America/New_York\n"
                "m,MARC,https://example.org,America/New_York\n",
                "routes.txt": "route_id,agency_id,route_long_name,route_type\n"
                "1,a,Acela,2\n2,a,Commuter Rail,2\n3,m,Commuter Rail,2\n",
                "stops.txt": "stop_id,stop_name\n",
                "trips.txt": "route_id,service_id,trip_id\n",
                "stop_times.txt": "trip_id,stop_id,stop_sequence\n",
                "calendar_dates.txt": "service_id,date,exception_type\n",
            }
        )
    )
    routes = list(feed.routes.values())
    labels = route_labels(feed, routes)
    assert labels == {"2": "Amtrak", "3": "MARC"}
    assert route_slugs(routes, labels)["3"] == "commuter-rail-marc"


def test_google_link():
    assert google_link(42.0, -73.5) == (
        "https://www.google.com/maps/search/?api=1&query=42.00000,-73.50000"
    )
    assert google_link(None, None) == ""


def test_brand_colors_pick_contrasting_text():
    assert brand_colors("0e4c92") == ("0E4C92", "FFFFFF")
    assert brand_colors("ffdd00") == ("FFDD00", "000000")
    assert brand_colors(None) is None


def test_rows_link_stops_to_google_maps():
    site = Site(slug="t", url="https://example.org/g.zip")
    feed = site_feed(fixture_zip("branching"), site)
    [(_, tables)] = site_timetables(feed, site, date(2026, 10, 5))
    days = day_views(feed, tables, "12h")
    rows = [row for day in days for table in day.tables for row in table.rows]
    assert rows
    assert all(row.google.startswith("https://www.google.com/maps/") for row in rows)


def test_days_sorted_by_runs():
    site = Site(slug="t", url="https://example.org/g.zip")
    feed = site_feed(fixture_zip("calendar-dates-only"), site)
    [(_, tables)] = site_timetables(feed, site, date(2026, 10, 5))
    views = day_views(feed, tables, "12h")
    assert [v.runs for v in views] == sorted((v.runs for v in views), reverse=True)
    assert views[0].runs == 3
    assert [t.anchor for t in views[0].tables] == [f"{views[0].anchor}-1"]
