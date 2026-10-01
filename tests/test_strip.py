from gtfs_zone_timetable_sites.strip import (
    MAX_LANES,
    endpoint_threshold,
    is_endpoint,
    route_graph,
    row_paths,
    stop_stats,
)


def lanes(graph):
    return [row.lane for row in graph.rows]


def test_straight_line_is_one_lane():
    graph = route_graph([(0, 1, 2, 3)], 4)
    assert graph.lane_count == 1
    assert lanes(graph) == [0, 0, 0, 0]
    assert all(not row.through for row in graph.rows)
    assert row_paths(graph, 0) == ["M20,50V100"]
    assert row_paths(graph, 3) == ["M20,0V50"]


def test_express_rejoining_the_line_stays_in_one_lane():
    graph = route_graph([(0, 1, 2, 3, 4), (0, 3, 4), (0, 2, 4)], 5)
    assert graph.lane_count == 1
    assert lanes(graph) == [0] * 5


def test_branch_gets_its_own_lane_and_merges_back():
    # D, C, B, A and D, E, B, A with E placed after C.
    graph = route_graph([(0, 1, 3, 4), (0, 2, 3, 4), (0, 1)], 5)
    assert graph.lane_count == 2
    assert lanes(graph) == [0, 0, 1, 0, 0]
    assert graph.rows[0].branches == (0, 1)
    assert graph.rows[1].through == (1,)
    assert graph.rows[2].through == (0,)
    # Echo curves back into the lane already reserved for Bravo.
    assert graph.rows[2].branches == (0,)
    assert graph.rows[3].merges == (0,)


def test_three_way_split_keeps_every_leg_drawn():
    # Trunk 0, legs 1-2, 3-4 and 5-6; the first two rejoin at 7, the third ends.
    graph = route_graph([(0, 1, 2, 7), (0, 3, 4, 7), (0, 5, 6)], 8)
    assert graph.lane_count == 3
    assert graph.rows[0].branches == (0, 1, 2)
    assert lanes(graph)[1:7] == [0, 0, 1, 1, 2, 2]
    assert set(graph.rows[1].through) == {1, 2}
    assert set(graph.rows[3].through) == {0, 2}
    assert graph.rows[4].branches == (0,)
    assert graph.rows[5].through == (0,)
    assert graph.rows[6].branches == ()
    assert graph.rows[7].merges == (0,)


def test_lanes_are_capped():
    legs = [(0, i) for i in range(1, MAX_LANES + 3)]
    graph = route_graph(legs, MAX_LANES + 3)
    assert graph.lane_count == MAX_LANES


def test_endpoints_and_minority_stops():
    trips = [(0, 1, 3, 4), (0, 1, 3, 4), (0, 2, 3, 4), (0, 1)]
    stats = stop_stats(trips, 5)
    threshold = endpoint_threshold(len(trips))
    assert [is_endpoint(s, threshold) for s in stats] == [
        True,
        True,
        False,
        False,
        True,
    ]
    assert stats[2].serves == 1
