import math
import re
from datetime import date
from itertools import pairwise

from conftest import fixture_files, make_zip

from cape_flier.build import build_site
from cape_flier.config import Site
from cape_flier.maps.svg import (
    WIDTH,
    Line,
    Mark,
    Projection,
    line_cells,
    line_class,
    overlaps,
    path_data,
    place_labels,
    render_map,
    simplify,
    tiles,
)

MONDAY = date(2026, 10, 5)


def test_simplify_drops_collinear_points():
    points = [(0.0, 0.0), (1.0, 0.1), (2.0, 0.0), (3.0, 5.0)]
    assert simplify(points, 1.0) == [(0.0, 0.0), (2.0, 0.0), (3.0, 5.0)]


def test_simplify_keeps_short_paths():
    assert simplify([(0.0, 0.0), (1.0, 1.0)], 1.0) == [(0.0, 0.0), (1.0, 1.0)]


def test_path_data_relative_and_compact():
    assert path_data([(10, 20), (13, 16), (13, 16), (8, 16)]) == "M10 20l3-4-5 0"


def test_path_data_single_point_draws_a_dot():
    assert path_data([(5, 5)]) == "M5 5l0 0"


def test_projection_fits_width_and_keeps_north_up():
    project = Projection([(42.0, -73.0), (42.1, -73.2)])
    north = project(42.1, -73.1)
    south = project(42.0, -73.1)
    assert north[1] < south[1]
    xs = [project(42.0, -73.0)[0], project(42.1, -73.2)[0]]
    assert min(xs) >= 0 and max(xs) <= WIDTH


def test_projection_of_one_point_has_a_frame():
    project = Projection([(42.0, -73.0)])
    assert project.height > 0
    x, y = project(42.0, -73.0)
    assert 0 <= x <= WIDTH and 0 <= y <= project.height


def test_line_class_swaps_colors_that_vanish():
    assert line_class(None) == "ink"
    assert line_class("FFFFFF") == "pale"
    assert line_class("000000") == "deep"
    assert line_class("0B57B0") == ""


def test_labels_avoid_lines():
    # Lines fill everything right of x=280, so only the left side is clear.
    cells = line_cells([[(280, y), (600, y)] for y in range(0, 200, 3)])
    placed = place_labels([(300.0, 100.0, Mark(0, 0, "Alpha"))], 200, cells)
    assert [side for _, side, _ in placed] == ["left"]


def test_labels_avoid_each_other():
    dots = [(300.0, 100.0, Mark(0, 0, "Alpha")), (300.0, 110.0, Mark(0, 0, "Bravo"))]
    boxes = [box for box, _, _ in place_labels(dots, 200, set())]
    assert len(boxes) == 2
    assert not overlaps(boxes[0], boxes[1])


def test_labels_off_the_map_are_dropped():
    dots = [(5.0, 5.0, Mark(0, 0, "A very long stop name indeed"))]
    placed = place_labels(dots, 10, set())
    assert placed == []


def test_render_map_empty_without_geometry():
    assert render_map("Nothing", [Line("R", None, ())], []) == ""


def test_render_map_escapes_labels():
    line = Line("R & S", "0B57B0", (((42.0, -73.0), (42.1, -73.1)),))
    svg = render_map("Map of R & S", [line], [Mark(42.0, -73.0, "<Main>", True)])
    assert 'aria-label="Map of R &amp; S"' in svg
    assert "&lt;Main&gt;" in svg
    assert 'stroke="#0B57B0"' in svg


def build(files: dict[str, str], **options) -> dict[str, str]:
    site = Site(slug="test", url="https://example.org/g.zip", **options)
    built = build_site(make_zip(files), site, today=MONDAY)
    return {path: body.decode() for path, body in built.items()}


def test_maps_from_stop_sequences_without_shapes():
    files = build(fixture_files("branching"))
    assert '<svg class="map"' in files["index.html"]
    route = files["4/index.html"]
    assert '<svg class="map"' in route
    assert ">Alpha</text>" in route


def test_bus_system_map_has_no_labels():
    files = fixture_files("branching")
    assert "<text" not in build(files)["index.html"]
    files["routes.txt"] = files["routes.txt"].replace("Forks,3", "Forks,2")
    assert ">Alpha</text>" in build(files)["index.html"]


def test_maps_use_shapes_when_present():
    files = fixture_files("branching")
    trips = files["trips.txt"].splitlines()
    files["trips.txt"] = "\n".join(
        [trips[0] + ",shape_id", *(row + ",S" for row in trips[1:])]
    )
    files["shapes.txt"] = (
        "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\n"
        "S,42.0,-73.0,1\nS,42.0,-73.6,2\nS,42.6,-73.6,3\n"
    )
    route = build(files)["4/index.html"]
    paths = re.findall(r'class="line[^"]*"[^>]* d="([^"]+)"', route)
    # One shape shared by every trip: one subpath, three points.
    assert len(paths) == 1
    assert paths[0].count("M") == 1
    assert len(re.findall(r"-?\d+", paths[0])) == 6


def test_map_none_leaves_maps_out():
    files = build(fixture_files("branching"), map="none")
    assert "<svg" not in files["index.html"]
    assert "<svg" not in files["4/index.html"]


def test_tiles_cover_the_map_box():
    project = Projection([(42.0, -73.0), (42.3, -73.4)])
    found = tiles(project)
    assert len({t.z for t in found}) == 1
    assert min(t.left for t in found) <= 0
    assert min(t.top for t in found) <= 0
    assert max(t.left + t.width for t in found) >= 100
    assert max(t.top + t.height for t in found) >= 100
    # Neighboring tiles abut exactly.
    row = sorted((t for t in found if t.y == found[0].y), key=lambda t: t.x)
    for a, b in pairwise(row):
        assert abs(a.left + a.width - b.left) < 1e-9


def test_tile_of_a_known_point():
    project = Projection([(42.2529, -73.7910)])
    z = tiles(project)[0].z
    n = 1 << z
    x = int((-73.7910 + 180) / 360 * n)
    lat = math.radians(42.2529)
    y = int((1 - math.log(math.tan(lat) + 1 / math.cos(lat)) / math.pi) / 2 * n)
    assert any((t.x, t.y) == (x, y) for t in tiles(project))


def test_basemap_wraps_svg_with_tiles_and_attribution():
    line = Line("R", "FF0000", (((42.0, -73.0), (42.1, -73.1)),))
    html = str(render_map("Map", [line], [], "stadia-toner"))
    assert html.startswith('<div class="map basemap" style="aspect-ratio:600/')
    assert 'loading="lazy"' in html
    assert "stamen_toner_lite" in html and "alidade_smooth_dark" in html
    assert '<svg class="over"' in html
    assert "OpenStreetMap" in html
    assert "<picture>" not in str(render_map("Map", [line], []))
