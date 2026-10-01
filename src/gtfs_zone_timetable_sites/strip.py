"""Rail strip for a timetable's stop column: lanes per branch, as in web-common.

Port of gtfs-zone-web-common's `gtfs/route-graph.ts` and the stats parts of
`gtfs/route-strip.ts`. Each pattern is the ascending row positions a trip
serves; consecutive pairs are the edges. A skip with an alternate path is an
express rejoining the line and gets no lane; one without is a branch.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

# Past this many lanes the outermost one is shared.
MAX_LANES = 5
# Share of trips starting or ending at a stop to call it a terminus.
ENDPOINT_SHARE = 0.05
# Below this share of trips a stop gets a trip count.
MINORITY_SHARE = 0.5
GUTTER_BASE = 40
LANE_WIDTH = 14
RAIL_WIDTH = 9


@dataclass(frozen=True, slots=True)
class RailRow:
    """Lanes at one row: the dot's lane, lanes passing, arriving and leaving."""

    lane: int
    through: tuple[int, ...]
    merges: tuple[int, ...]
    branches: tuple[int, ...]
    exiting: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RouteGraph:
    rows: tuple[RailRow, ...]
    lane_count: int


@dataclass(frozen=True, slots=True)
class StopStats:
    starts: int
    ends: int
    serves: int


def edges_of(patterns: Sequence[Sequence[int]]) -> dict[int, set[int]]:
    """Every forward step any pattern takes, deduped."""
    edges: dict[int, set[int]] = {}
    for positions in patterns:
        for a, b in pairwise(positions):
            if b > a:
                edges.setdefault(a, set()).add(b)
    return edges


def has_alternate_path(edges: dict[int, set[int]], start: int, end: int) -> bool:
    """Whether `end` is reachable from `start` without the direct edge."""
    stack = [n for n in edges.get(start, ()) if n < end]
    seen: set[int] = set()
    while stack:
        at = stack.pop()
        if at == end:
            return True
        if at in seen:
            continue
        seen.add(at)
        stack += [n for n in edges.get(at, ()) if n <= end and n not in seen]
    return False


def structural_edges(edges: dict[int, set[int]]) -> dict[int, list[int]]:
    """Trunk steps plus skips with no other way through."""
    kept = {}
    for start, targets in edges.items():
        survivors = sorted(
            end
            for end in targets
            if end == start + 1 or not has_alternate_path(edges, start, end)
        )
        if survivors:
            kept[start] = survivors
    return kept


def route_graph(patterns: Sequence[Sequence[int]], size: int) -> RouteGraph:
    """Lane sweep: the leftmost lane reserved for a row wins, the rest merge
    into it, then the row's outgoing edges reserve lanes going down."""
    kept = structural_edges(edges_of(patterns))
    rows = []
    lanes: list[int | None] = []
    lane_count = 0

    def reserve(target: int) -> int:
        if None in lanes:
            free = lanes.index(None)
            lanes[free] = target
            return free
        if len(lanes) < MAX_LANES:
            lanes.append(target)
            return len(lanes) - 1
        last = MAX_LANES - 1
        held = lanes[last]
        lanes[last] = target if held is None else min(held, target)
        return last

    for i in range(size):
        merges = [lane for lane, held in enumerate(lanes) if held == i]
        for lane in merges:
            lanes[lane] = None
        lane = merges[0] if merges else reserve(i)
        if not merges:
            lanes[lane] = None

        branches: list[int] = []
        claimed: set[int] = set()
        for end in kept.get(i, ()):
            if end in lanes:
                existing = lanes.index(end)
                if existing not in branches:
                    branches.append(existing)
                continue
            if not branches:
                target = lane
                lanes[lane] = end
            else:
                target = reserve(end)
            claimed.add(target)
            if target not in branches:
                branches.append(target)

        # A converged lane still carries what reserved it, so it passes through.
        through = [
            other
            for other, held in enumerate(lanes)
            if held is not None and other != lane and other not in claimed
        ]
        lane_count = max(lane_count, lane + 1, *(n + 1 for n in branches + through))
        rows.append(
            RailRow(
                lane=lane,
                through=tuple(through),
                merges=tuple(merges),
                branches=tuple(branches),
                exiting=tuple(dict.fromkeys([*through, *branches])),
            )
        )
    return RouteGraph(rows=tuple(rows), lane_count=max(1, lane_count))


def lane_x(lane: int) -> int:
    return GUTTER_BASE // 2 + lane * LANE_WIDTH


def gutter_width(lane_count: int) -> int:
    return GUTTER_BASE + (lane_count - 1) * LANE_WIDTH


def vertical_path(lane: int) -> str:
    x = lane_x(lane)
    return f"M{x},0V100"


def merge_path(lane: int, into: int) -> str:
    """From `lane` at the top of the row into `into` at its centre."""
    x0, x1 = lane_x(lane), lane_x(into)
    if lane == into:
        return f"M{x1},0V50"
    return f"M{x0},0C{x0},20 {x1},30 {x1},50"


def branch_path(start: int, lane: int) -> str:
    """From `start` at the row's centre out into `lane` at the bottom."""
    x0, x1 = lane_x(start), lane_x(lane)
    if lane == start:
        return f"M{x0},50V100"
    return f"M{x0},50C{x0},80 {x1},70 {x1},100"


def row_paths(graph: RouteGraph, index: int) -> list[str]:
    row = graph.rows[index]
    return [
        *(vertical_path(lane) for lane in row.through),
        *(merge_path(lane, row.lane) for lane in row.merges),
        *(branch_path(row.lane, lane) for lane in row.branches),
    ]


def stop_stats(patterns: Sequence[Sequence[int]], size: int) -> list[StopStats]:
    """Per row, trips starting, ending and calling there; one pattern per trip."""
    starts, ends, serves = [0] * size, [0] * size, [0] * size
    for positions in patterns:
        if not positions:
            continue
        starts[positions[0]] += 1
        ends[positions[-1]] += 1
        for position in set(positions):
            serves[position] += 1
    return [StopStats(*counts) for counts in zip(starts, ends, serves, strict=True)]


def endpoint_threshold(total_trips: int) -> float:
    return max(1, total_trips * ENDPOINT_SHARE)


def is_endpoint(stats: StopStats, threshold: float) -> bool:
    return stats.starts >= threshold or stats.ends >= threshold


def is_minority(stats: StopStats, total_trips: int) -> bool:
    share = stats.serves / total_trips if total_trips else 1
    return share < MINORITY_SHARE
