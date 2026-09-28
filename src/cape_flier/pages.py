"""Timetables and routes to plain data the templates render."""

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time
from itertools import groupby
from zoneinfo import ZoneInfo

from cape_flier.colors import route_color
from cape_flier.config import TimeFormat
from cape_flier.gtfs.reader import Feed, Route
from cape_flier.gtfs.service import (
    DayType,
    dates_label,
    day_order,
    missing_label,
    trip_note,
)
from cape_flier.strip import (
    RailRow,
    endpoint_threshold,
    gutter_width,
    is_endpoint,
    lane_x,
    route_graph,
    row_paths,
    stop_stats,
)
from cape_flier.timetable import Cell, Column, Timetable

DAY_SECONDS = 24 * 3600
# Minimum WCAG contrast for badge text on the route color.
MIN_CONTRAST = 4.5
# Arrival and departure are both shown when they differ by more than this.
DWELL_SECONDS = 60


def tidy(text: str) -> str:
    """Collapse runs of whitespace and trim."""
    return " ".join(text.split())


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def short_date(day: date) -> str:
    return f"{day:%b} {day.day}"


def luminance(color: str) -> float:
    """WCAG relative luminance of an RRGGBB color."""
    channels = []
    for i in (0, 2, 4):
        c = int(color[i : i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def text_color(background: str, text: str | None = None) -> str:
    """`text` when it contrasts enough with `background`, else black or white,
    whichever contrasts more."""
    if text is None or contrast(background, text) < MIN_CONTRAST:
        text = max(("000000", "FFFFFF"), key=lambda t: contrast(background, t))
    return text


def badge_colors(route: Route) -> tuple[str, str]:
    """(background, text) for a route badge: the feed's color or a hashed one,
    keeping the feed's text color only when it contrasts enough."""
    color = route_color(route.route_id, route.color)
    return color, text_color(color, route.text_color)


# Basic GTFS route types, then extended ones as (first, last) ranges.
MODES = {
    0: "light rail",
    1: "subway",
    2: "train",
    3: "bus",
    4: "ferry",
    5: "cable car",
    6: "gondola",
    7: "funicular",
    11: "trolleybus",
    12: "monorail",
}
EXTENDED_MODES = (
    (100, 199, "train"),
    (200, 299, "bus"),
    (400, 499, "subway"),
    (700, 799, "bus"),
    (800, 800, "trolleybus"),
    (900, 999, "light rail"),
    (1000, 1099, "ferry"),
    (1300, 1399, "gondola"),
    (1400, 1499, "funicular"),
)


def mode_name(route_type: int) -> str:
    """'bus', 'train' and so on for a route type, else 'transit'."""
    if route_type in MODES:
        return MODES[route_type]
    for first, last, name in EXTENDED_MODES:
        if first <= route_type <= last:
            return name
    return "transit"


def join_and(items: Sequence[str]) -> str:
    """'A', 'A and B', 'A, B and C'."""
    if len(items) < 2:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def modes_label(modes: list[str]) -> str:
    """'Bus', 'Bus and train', 'Bus, ferry and train' from mode names."""
    text = join_and(sorted(set(modes)) or ["transit"])
    return text[:1].upper() + text[1:]


def breadcrumbs(items: list[tuple[str, str]]) -> dict:
    """schema.org BreadcrumbList from (name, url) pairs, outermost first."""
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i, "name": name, "item": url}
            for i, (name, url) in enumerate(items, 1)
        ],
    }


def brand_colors(color: str | None) -> tuple[str, str] | None:
    """(background, text) for a site's brand color."""
    if color is None:
        return None
    return color.upper(), text_color(color)


@dataclass(frozen=True, slots=True)
class TimeText:
    """A time as shown in a cell: clock text plus how to style it."""

    text: str
    pm: bool
    # Days past the service day: +1 after midnight, -1 the evening before.
    days: int


def clock(seconds: int, time_format: TimeFormat) -> TimeText:
    """Clock time without a/p; PM is marked for bolding in 12h tables."""
    minutes = seconds // 60
    days, rest = divmod(minutes, 24 * 60)
    hours, minute = divmod(rest, 60)
    if time_format == "24h":
        return TimeText(f"{hours:02d}:{minute:02d}", False, days)
    return TimeText(f"{(hours - 1) % 12 + 1}:{minute:02d}", hours >= 12, days)


def clock_label(seconds: int, time_format: TimeFormat) -> str:
    """Clock time with a/p for prose, e.g. '7:30 PM'."""
    shown = clock(seconds, time_format)
    label = shown.text
    if time_format == "12h":
        label += " PM" if shown.pm else " AM"
    if shown.days:
        label += f" {shown.days:+d}"
    return label


@dataclass(frozen=True, slots=True)
class CellView:
    time: TimeText | None
    untimed: bool
    mark: str
    arrival: TimeText | None = None


@dataclass(frozen=True, slots=True)
class ColumnHead:
    number: str
    headsign: str
    every: str
    shaded: bool
    note: str = ""
    bikes: bool = False
    wheelchair: bool = False


@dataclass(frozen=True, slots=True)
class HeadsignSpan:
    text: str
    span: int
    shaded: bool


@dataclass(frozen=True, slots=True)
class RowView:
    name: str
    zone: str
    cells: tuple[CellView, ...]
    google: str = ""
    paths: tuple[str, ...] = ()
    rail: str = ""
    dot_x: int = 0
    solid: bool = False
    wheelchair: bool = False


@dataclass(frozen=True, slots=True)
class Key:
    """A legend entry, led by an icon when `icon` is set."""

    icon: str
    text: str


@dataclass(frozen=True, slots=True)
class TableView:
    title: str
    heads: tuple[ColumnHead, ...]
    headsigns: tuple[HeadsignSpan, ...]
    show_numbers: bool
    show_headsigns: bool
    show_notes: bool
    rows: tuple[RowView, ...]
    legend: tuple[Key, ...]
    anchor: str = ""
    trips: int = 0
    gutter: int = 0

    @property
    def show_amenities(self) -> bool:
        return any(head.bikes or head.wheelchair for head in self.heads)


@dataclass(frozen=True, slots=True)
class DayView:
    anchor: str
    name: str
    notes: tuple[str, ...]
    tables: tuple[TableView, ...]
    runs: int = 0
    first: str = ""
    last: str = ""

    @property
    def trips(self) -> int:
        return sum(table.trips for table in self.tables)

    @property
    def icons(self) -> bool:
        return any(key.icon for table in self.tables for key in table.legend)


@dataclass(frozen=True, slots=True)
class RouteView:
    route_id: str
    slug: str
    badge: str
    name: str
    colors: tuple[str, str] | None
    days: tuple[str, ...]
    url: str
    desc: str
    mode: str = "transit"
    endpoints: tuple[str, str] | None = None

    @property
    def line_color(self) -> str | None:
        return self.colors[0] if self.colors else None

    @property
    def title(self) -> str:
        return f"{self.badge} {self.name}" if self.name else self.badge

    @property
    def days_label(self) -> str:
        return join_and(self.days)


def cell_view(cell: Cell | None, time_format: TimeFormat) -> CellView:
    if cell is None:
        return CellView(None, False, "")
    mark = ""
    if not cell.pickup and cell.drop_off:
        mark = "d"
    elif cell.pickup and not cell.drop_off:
        mark = "p"
    if cell.request:
        mark += "f"
    if cell.time is None:
        return CellView(None, True, mark)
    arrival = None
    if (
        cell.arrival is not None
        and cell.departure is not None
        and cell.departure - cell.arrival > DWELL_SECONDS
    ):
        arrival = clock(cell.arrival, time_format)
    return CellView(clock(cell.time, time_format), False, mark, arrival)


def column_head(column: Column, time_format: TimeFormat, shaded: bool) -> ColumnHead:
    every = ""
    if column.headway is not None:
        minutes = column.headway.headway_secs // 60
        until = clock_label(column.headway.end, time_format)
        every = f"then every {minutes} min until {until}"
    return ColumnHead(
        number=tidy(column.short_name),
        headsign=tidy(column.headsign),
        every=every,
        shaded=shaded,
    )


def zone_label(zone: str | None, day: date) -> str:
    """The zone's abbreviation on `day`, e.g. 'CDT', else its name."""
    if not zone:
        return ""
    name = datetime.combine(day, time(12), ZoneInfo(zone)).tzname()
    return name if name and not name.startswith(("+", "-")) else zone


def hour_shading(columns: tuple[Column, ...]) -> list[bool]:
    """Alternate shading each time the hour of the first time changes."""
    shading = []
    shaded, hour = True, None
    for column in columns:
        first = column.first_time()
        this_hour = None if first is None else first // 3600
        if this_hour != hour:
            shaded, hour = not shaded, this_hour
        shading.append(shaded)
    return shading


# Headsigns naming a service or a loop rather than a place to head to.
NOT_A_PLACE = re.compile(
    r"\b(loop|clockwise|counterclockwise|inbound|outbound|train|special)\b", re.I
)


def headsign_spans(heads: tuple[ColumnHead, ...]) -> tuple[HeadsignSpan, ...]:
    """Adjacent columns with the same headsign share one header cell."""
    spans = []
    for text, group in groupby(heads, key=lambda head: head.headsign):
        run = list(group)
        spans.append(HeadsignSpan(text, len(run), all(head.shaded for head in run)))
    return tuple(spans)


def table_title(headsigns: list[str]) -> str:
    """'To A / B', without 'To' when a headsign is not a destination."""
    text = " / ".join(headsigns)
    if any(NOT_A_PLACE.search(h) or not h[:1].isalnum() for h in headsigns):
        return text
    return f"To {text}"


def google_link(lat: float | None, lon: float | None) -> str:
    """Google Maps URL for a point, empty without coordinates."""
    if lat is None or lon is None:
        return ""
    return f"https://www.google.com/maps/search/?api=1&query={lat:.5f},{lon:.5f}"


def stop_link(feed: Feed, stop_id: str) -> str:
    stop = feed.stops.get(stop_id)
    return google_link(stop.lat, stop.lon) if stop else ""


def straight(row: RailRow) -> bool:
    """Whether the row is only lane 0 running straight, drawn by CSS."""
    return (
        row.lane == 0
        and not row.through
        and row.merges in ((), (0,))
        and row.branches in ((), (0,))
    )


def rail_class(row: RailRow) -> str:
    """CSS halves of a straight row's rail: 'u' above the dot, 'd' below."""
    if not straight(row):
        return ""
    return " ".join(half for half, on in (("u", row.merges), ("d", row.branches)) if on)


# name -> (icon, legend text, feed note when all are 1, feed note when all are 2).
AMENITIES = {
    "bikes": (
        "bike",
        "Bikes allowed",
        "Bikes allowed on all trips.",
        "No bikes on any trip.",
    ),
    "trips": (
        "wheelchair",
        "Wheelchair accessible trip",
        "All trips are wheelchair accessible.",
        "No trips are wheelchair accessible.",
    ),
    "stops": (
        "wheelchair",
        "Wheelchair accessible stop",
        "All stops are wheelchair accessible.",
        "No stops are wheelchair accessible.",
    ),
}


def feed_amenities(
    tables: list[Timetable],
) -> tuple[tuple[str, ...], frozenset[str]]:
    """(feed notes, amenities to mark with icons) over every table: a note
    when all trips or stops are 1 or all 2, icons when they differ."""
    values = {
        "bikes": {column.bikes for table in tables for column in table.columns},
        "trips": {column.wheelchair for table in tables for column in table.columns},
        "stops": {row.wheelchair for table in tables for row in table.rows},
    }
    notes = []
    marked = set()
    for name, found in values.items():
        _, _, yes, no = AMENITIES[name]
        if found == {1}:
            notes.append(yes)
        elif found == {2}:
            notes.append(no)
        elif 1 in found:
            marked.add(name)
    return tuple(notes), frozenset(marked)


def table_view(
    feed: Feed,
    table: Timetable,
    time_format: TimeFormat,
    anchor: str = "",
    marked: frozenset[str] = frozenset(),
) -> TableView:
    notes = [trip_note(table.day_type, column.trip_id) for column in table.columns]
    letters = {
        note: chr(ord("A") + i)
        for i, note in enumerate(dict.fromkeys(note for note in notes if note))
    }
    shown = [i for i, row in enumerate(table.rows) if row.timepoint]
    heads = tuple(
        replace(
            column_head(column, time_format, shaded),
            note=letters.get(note, ""),
            bikes="bikes" in marked and column.bikes == 1,
            wheelchair="trips" in marked and column.wheelchair == 1,
        )
        for column, shaded, note in zip(
            table.columns, hour_shading(table.columns), notes, strict=True
        )
    )
    # Each column's served rows, indexed among the shown rows.
    patterns = [
        [k for k, i in enumerate(shown) if column.cells[i] is not None]
        for column in table.columns
    ]
    graph = route_graph(list(dict.fromkeys(map(tuple, patterns))), len(shown))
    stats = stop_stats(patterns, len(shown))
    total = len(table.columns)
    threshold = endpoint_threshold(total)
    rows = tuple(
        RowView(
            name=tidy(table.rows[i].name),
            zone=zone_label(table.rows[i].timezone, table.day_type.start),
            cells=tuple(
                cell_view(column.cells[i], time_format) for column in table.columns
            ),
            google=stop_link(feed, table.rows[i].stop_id),
            paths=() if straight(graph.rows[k]) else tuple(row_paths(graph, k)),
            rail=rail_class(graph.rows[k]),
            dot_x=lane_x(graph.rows[k].lane),
            solid=is_endpoint(stats[k], threshold),
            wheelchair="stops" in marked and table.rows[i].wheelchair == 1,
        )
        for k, i in enumerate(shown)
    )
    cells = [cell for row in rows for cell in row.cells]
    legend = [f"{letter}: {note}." for note, letter in letters.items()]
    if time_format == "12h" and any(c.time and c.time.pm for c in cells):
        legend.append("PM times are in bold.")
    shown_times = [t for c in cells for t in (c.time, c.arrival) if t]
    days = {t.days for t in shown_times if t.days}
    if days == {1}:
        legend.append("+1: after midnight, the next day.")
    elif any(d > 0 for d in days):
        legend.append("+n: after midnight, n days later.")
    if any(d < 0 for d in days):
        legend.append("-1: the evening before.")
    if any(c.untimed for c in cells):
        legend.append("|: stops here, no scheduled time.")
    if any("d" in c.mark for c in cells):
        legend.append("d: drop off only.")
    if any("p" in c.mark for c in cells):
        legend.append("p: pick up only.")
    if any("f" in c.mark for c in cells):
        legend.append("f: flag stop, stops only on request.")
    if any(c.arrival for c in cells):
        legend.append("Two times: arrives, then departs.")
    shown_icons = {
        "bikes": any(head.bikes for head in heads),
        "trips": any(head.wheelchair for head in heads),
        "stops": any(row.wheelchair for row in rows),
    }
    keys = [
        Key(icon, text)
        for name, (icon, text, _, _) in AMENITIES.items()
        if shown_icons[name]
    ]
    headsigns = [tidy(h) for h in table.headsigns]
    # Trip numbers repeated on every trip (often the route name) add nothing.
    return TableView(
        title=table_title(headsigns),
        heads=heads,
        headsigns=headsign_spans(heads),
        show_numbers=len({head.number for head in heads}) > 1,
        show_headsigns=len({head.headsign for head in heads}) > 1,
        show_notes=bool(letters),
        rows=rows,
        legend=(*keys, *(Key("", text) for text in legend)),
        anchor=anchor,
        trips=len(table.columns),
        gutter=gutter_width(graph.lane_count),
    )


def day_notes(day: DayType) -> tuple[str, ...]:
    if not day.regular:
        listed = dates_label(day.dates)
        # A name like 'Weekday, Oct 12 to Oct 16' already says it all.
        return (f"Runs only on {listed}.",) if day.name == listed else ()
    notes = []
    if day.missing:
        notes.append(f"No service {missing_label(day)}.")
    if day.extra:
        notes.append(f"Also runs {dates_label(day.extra)}.")
    return tuple(notes)


def runs(table: Timetable) -> int:
    """Trips run over the horizon: each trip once per date it runs."""
    return sum(len(table.day_type.trip_dates(c.trip_id)) for c in table.columns)


def trip_span(tables: list[Timetable]) -> tuple[int, int] | None:
    """Earliest and latest trip start over the tables; a frequency column's
    last start is the last headway before its end."""
    starts = []
    for table in tables:
        for column in table.columns:
            if (headway := column.headway) is not None:
                gap = headway.headway_secs
                last = headway.start + (headway.end - headway.start - 1) // gap * gap
                starts += [headway.start, max(headway.start, last)]
            elif (first := column.first_time()) is not None:
                starts.append(first)
    return (min(starts), max(starts)) if starts else None


def endpoints(tables: list[Timetable]) -> tuple[str, str] | None:
    """First and last timepoint names of the busiest table, when they differ."""
    if not tables:
        return None
    busiest = max(tables, key=runs)
    names = [tidy(row.name) for row in busiest.rows if row.timepoint]
    if len(names) < 2 or names[0] == names[-1]:
        return None
    return names[0], names[-1]


def day_views(
    feed: Feed,
    tables: list[Timetable],
    time_format: TimeFormat,
    marked: frozenset[str] = frozenset(),
) -> list[DayView]:
    """Tables grouped by day type, busiest first by runs over the horizon;
    within a day, busiest table first."""
    by_day: dict[DayType, list[Timetable]] = {}
    for table in tables:
        by_day.setdefault(table.day_type, []).append(table)
    day_runs = {day: sum(runs(t) for t in group) for day, group in by_day.items()}
    views = []
    anchors: set[str] = set()
    for day in sorted(by_day, key=lambda d: (-day_runs[d], day_order(d))):
        anchor = slugify(day.name) or "day"
        while anchor in anchors:
            anchor += "-2"
        anchors.add(anchor)
        group = sorted(by_day[day], key=lambda t: (-runs(t), t.direction_id or 0))
        span = trip_span(group)
        views.append(
            DayView(
                anchor=anchor,
                name=day.name,
                notes=day_notes(day),
                tables=tuple(
                    table_view(feed, t, time_format, f"{anchor}-{i + 1}", marked)
                    for i, t in enumerate(group)
                ),
                runs=day_runs[day],
                first=clock_label(span[0], time_format) if span else "",
                last=clock_label(span[1], time_format) if span else "",
            )
        )
    return views


def route_labels(feed: Feed, routes: list[Route]) -> dict[str, str]:
    """route_id -> its agency's name, for routes whose name another agency's
    route shares; e.g. two agencies' 'Commuter Rail'."""
    agencies: dict[str, set[str]] = {}
    for route in routes:
        agencies.setdefault(tidy(route.name), set()).add(route.agency_id)
    return {
        route.route_id: tidy(agency.name)
        for route in routes
        if len(agencies[tidy(route.name)]) > 1
        and (agency := feed.agencies.get(route.agency_id))
    }


def route_view(
    route: Route, slug: str, tables: list[Timetable], label: str = ""
) -> RouteView:
    short, long = tidy(route.short_name), tidy(route.long_name)
    name = long if short else ""
    if label:
        name = f"{name} ({label})" if name else label
    days: list[str] = []
    for day in sorted({t.day_type for t in tables}, key=day_order):
        if day.regular and day.name not in days:
            days.append(day.name)
    return RouteView(
        route_id=route.route_id,
        slug=slug,
        badge=short or long or route.route_id,
        name=name,
        colors=badge_colors(route),
        days=tuple(days),
        url=route.url,
        desc=tidy(route.desc),
        mode=mode_name(route.route_type),
        endpoints=endpoints(tables),
    )


def route_slugs(routes: list[Route], labels: dict[str, str]) -> dict[str, str]:
    """route_id -> a unique URL slug from the route's name and label."""
    slugs: dict[str, str] = {}
    taken: set[str] = set()
    for route in routes:
        text = f"{route.name} {labels.get(route.route_id, '')}"
        base = slugify(text) or slugify(route.route_id) or "route"
        slug = base
        n = 2
        while slug in taken:
            slug = f"{base}-{n}"
            n += 1
        taken.add(slug)
        slugs[route.route_id] = slug
    return slugs


def valid_through(feed: Feed, today: date) -> date | None:
    """The last date the feed has service, from feed_info or the calendars;
    None when that is over a year out, as placeholder end dates often are."""
    end = feed_end(feed)
    if end is None or (end - today).days > 366:
        return None
    return end


def feed_end(feed: Feed) -> date | None:
    if feed.feed_info and feed.feed_info.end:
        return feed.feed_info.end
    ends = [calendar.end for calendar in feed.calendars.values()]
    ends += [
        day
        for exceptions in feed.calendar_dates.values()
        for day, added in exceptions.items()
        if added
    ]
    return max(ends, default=None)
