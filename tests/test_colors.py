import pytest

from gtfs_zone_timetable_sites.colors import route_color

# Expected values from routeColor in gtfs-zone-web-common/src/gtfs/route-colors.ts.
PARITY = [
    ("1", "5B87C8"),
    ("2", "BF6C57"),
    ("100", "BC704A"),
    ("L", "BE6876"),
    ("N", "807CC5"),
    ("Red", "9E71B5"),
    ("", "BB6883"),
    ("Orange Line Express Weekday Service 2026", "1F9B82"),
    ("zzzzzzzzzzzzzzzzzzzz", "99862C"),
    ("Métro", "BF6B60"),
    ("bus-\U0001f68c", "7D903E"),
]


@pytest.mark.parametrize(("route_id", "expected"), PARITY)
def test_hashed_color_matches_web_common(route_id, expected):
    assert route_color(route_id, None) == expected


def test_feed_color_is_kept():
    assert route_color("1", "002599") == "002599"
