"""A mode's routes split into system maps by grid density: clusters of cells
served by two or more routes become local maps, routes mostly outside them
long maps grouped by overlap."""

import math
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from itertools import pairwise

type Path = Sequence[tuple[float, float]]
type Cell = tuple[int, int]
type Split = list[tuple[str, list[int]]]

# Spacing of the points each route is resampled to, in km.
STEP_KM = 0.25
# Grid cell side in km for density and for overlap.
DENSITY_CELL = 1.0
OVERLAP_CELL = 0.5
# Share of a route's samples that must fall in a cluster for it to belong there.
INSIDE_SHARE = 0.6
# Cells two routes must share to count as overlapping.
MIN_SHARED = 3
# One map instead past this many maps, or when the largest local map holds
# under this share of the routes.
MAX_MAPS = 4
MIN_LOCAL_SHARE = 0.5


def resample(
    path: Sequence[tuple[float, float]], step: float
) -> list[tuple[float, float]]:
    """Points every `step` km along a planar path, ends included."""
    if len(path) < 2:
        return list(path)
    out = [path[0]]
    carry = 0.0
    for (ax, ay), (bx, by) in pairwise(path):
        seg = math.hypot(bx - ax, by - ay)
        pos = step - carry
        while pos <= seg:
            t = pos / seg
            out.append((ax + (bx - ax) * t, ay + (by - ay) * t))
            pos += step
        carry = (carry + seg) % step
    out.append(path[-1])
    return out


def samples(routes: Sequence[Sequence[Path]]) -> list[list[tuple[float, float]]]:
    """Each route's (lat, lon) paths resampled in km on a plane centered on
    all the routes."""
    points = [p for paths in routes for path in paths for p in path]
    lat0 = sum(p[0] for p in points) / len(points)
    lon0 = sum(p[1] for p in points) / len(points)
    kx = 111.32 * math.cos(math.radians(lat0))
    return [
        [
            point
            for path in paths
            for point in resample(
                [((lon - lon0) * kx, (lat - lat0) * 110.57) for lat, lon in path],
                STEP_KM,
            )
        ]
        for paths in routes
    ]


def cells(points: Sequence[tuple[float, float]], side: float) -> Counter[Cell]:
    return Counter((int(x // side), int(y // side)) for x, y in points)


def components(
    nodes: Sequence[int], linked: Callable[[int, int], bool]
) -> list[list[int]]:
    """Connected components of `nodes` under `linked`, largest first."""
    parent = {n: n for n in nodes}

    def find(n: int) -> int:
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    for i, a in enumerate(nodes):
        for b in nodes[i + 1 :]:
            if find(a) != find(b) and linked(a, b):
                parent[find(a)] = find(b)
    out: dict[int, list[int]] = defaultdict(list)
    for n in nodes:
        out[find(n)].append(n)
    return sorted(out.values(), key=lambda c: (-len(c), c[0]))


def clusters(per_route: Sequence[Counter[Cell]]) -> dict[Cell, int]:
    """Cells served by two or more routes, grown by one cell, labeled by
    connected cluster."""
    served: Counter[Cell] = Counter()
    for c in per_route:
        served.update(c.keys())
    dense = {cell for cell, n in served.items() if n >= 2}
    grown = {
        (x + dx, y + dy) for x, y in dense for dx in (-1, 0, 1) for dy in (-1, 0, 1)
    }
    label: dict[Cell, int] = {}
    cluster = -1
    for start in sorted(grown):
        if start in label:
            continue
        cluster += 1
        label[start] = cluster
        stack = [start]
        while stack:
            x, y = stack.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    n = (x + dx, y + dy)
                    if n in grown and n not in label:
                        label[n] = cluster
                        stack.append(n)
    return label


def split_routes(routes: Sequence[Sequence[Path]]) -> Split:
    """Route indexes per map as (kind, indexes), kind "local", "long" or
    "all": local maps largest first, then long routes grouped by overlap,
    with the routes overlapping no other long route sharing one map."""
    whole: Split = [("all", list(range(len(routes))))]
    if len(routes) < 3:
        return whole
    points = samples(routes)
    per_route = [cells(p, DENSITY_CELL) for p in points]
    label = clusters(per_route)
    local: dict[int, list[int]] = defaultdict(list)
    long = []
    for i, c in enumerate(per_route):
        inside: Counter[int] = Counter()
        for cell, n in c.items():
            if cell in label:
                inside[label[cell]] += n
        best = inside.most_common(1)
        if best and best[0][1] >= INSIDE_SHARE * c.total():
            local[best[0][0]].append(i)
        else:
            long.append(i)
    overlap = {i: set(cells(points[i], OVERLAP_CELL)) for i in long}
    groups = components(long, lambda a, b: len(overlap[a] & overlap[b]) >= MIN_SHARED)
    loose = sorted(i for g in groups if len(g) == 1 for i in g)
    split = [
        ("local", c) for c in sorted(local.values(), key=lambda c: (-len(c), c[0]))
    ]
    split += [("long", g) for g in groups if len(g) > 1]
    if loose:
        split.append(("long", loose))
    largest = max((len(ix) for kind, ix in split if kind == "local"), default=0)
    if not 1 < len(split) <= MAX_MAPS or largest < MIN_LOCAL_SHARE * len(routes):
        return whole
    return split
