"""build_site: the only entry point from a GTFS zip to a site's files."""

import io
import json
import zipfile
from datetime import date
from importlib.metadata import version

from cape_flier.config import Site
from cape_flier.gtfs.reader import Feed, Route, read_feed
from cape_flier.gtfs.service import day_types, horizon_start
from cape_flier.maps.svg import route_map, system_map
from cape_flier.pages import (
    brand_colors,
    day_views,
    route_labels,
    route_slugs,
    route_view,
    tidy,
    valid_through,
)
from cape_flier.render import asset, render
from cape_flier.timetable import Timetable, route_timetables

BASE_URL = "https://sites.gtfs.zone"
LIST_URL = "https://list.gtfs.zone"


def is_bus(route_type: int) -> bool:
    """Bus and trolleybus, in basic and extended GTFS route types."""
    return route_type in (3, 11) or 700 <= route_type < 800 or route_type == 800


def site_feed(zip_bytes: bytes, site: Site) -> Feed:
    """The feed with only the routes the site's filter accepts."""
    return read_feed(
        zip_bytes, keep_route=lambda r: site.routes.accepts(r.route_id, r.route_type)
    )


def route_order(route: Route) -> tuple[int, int, str, str]:
    """route_sort_order, then numeric short names in number order, then name."""
    number = route.short_name.isdigit()
    return (
        route.sort_order if route.sort_order is not None else 1 << 30,
        int(route.short_name) if number else 1 << 30,
        route.name,
        route.route_id,
    )


def site_timetables(
    feed: Feed, site: Site, today: date
) -> list[tuple[Route, list[Timetable]]]:
    """Every route's timetables over the site's horizon from `today`."""
    start = horizon_start(feed, today)
    result = []
    for route in sorted(feed.routes.values(), key=route_order):
        trip_ids = [
            t.trip_id for t in feed.trips.values() if t.route_id == route.route_id
        ]
        types = day_types(feed, trip_ids, start, site.horizon_days)
        tables = route_timetables(feed, route.route_id, types, site.timepoints)
        if tables:
            result.append((route, tables))
    return result


def build_site(
    zip_bytes: bytes, site: Site, today: date | None = None
) -> dict[str, bytes]:
    """Map of path (relative to the site root) to file contents. No I/O."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        bad = archive.testzip()
    if bad is not None:
        raise ValueError(f"corrupt member in GTFS zip: {bad}")
    today = today or date.today()
    feed = site_feed(zip_bytes, site)
    timetables = site_timetables(feed, site, today)
    labels = route_labels(feed, [route for route, _ in timetables])
    slugs = route_slugs([route for route, _ in timetables], labels)
    agencies = list(feed.agencies.values())
    base_url = f"{BASE_URL}/{site.slug}/"
    common = {
        "site_title": site.title or (tidy(agencies[0].name) if agencies else site.slug),
        "base_url": base_url,
        "generated": today,
        "brand": brand_colors(site.brand_color),
    }

    routes = [
        route_view(route, slugs[route.route_id], tables, labels.get(route.route_id, ""))
        for route, tables in timetables
    ]
    through = valid_through(feed, today)
    maps = site.map == "svg"
    system_routes = [
        (view.title, view.line_color, tables, f"{view.slug}/")
        for view, (_, tables) in zip(routes, timetables, strict=True)
    ]
    # Bus systems have too many stops to label legibly at system scale.
    buses = all(is_bus(route.route_type) for route, _ in timetables)
    home_map = (
        system_map(feed, common["site_title"], system_routes, site.basemap, not buses)
        if maps
        else ""
    )
    files = {
        "index.html": render(
            "index.html",
            **common,
            agencies=agencies,
            routes=routes,
            map=home_map,
            valid_through=through,
            feed_url=f"{LIST_URL}/#feed={site.feed}" if site.feed else "",
            root="",
        )
    }
    for view, (_, tables) in zip(routes, timetables, strict=True):
        route_svg = (
            route_map(feed, view.title, view.line_color, tables, site.basemap)
            if maps
            else ""
        )
        files[f"{view.slug}/index.html"] = render(
            "route.html",
            **common,
            route=view,
            map=route_svg,
            days=day_views(feed, tables, site.time_format),
            root="../",
        )
    files["site.json"] = summary_json(
        slug=site.slug,
        title=common["site_title"],
        routes=len(routes),
        valid_through=through.isoformat() if through else None,
        generated=today.isoformat(),
    )
    files["style.css"] = asset("style.css")
    files["logo.svg"] = asset("logo.svg")
    files["sitemap.xml"] = render(
        "sitemap.xml",
        base_url=base_url,
        paths=["", *(f"{view.slug}/" for view in routes)],
        generated=today,
    )
    return files


def summary_json(**fields: object) -> bytes:
    """A site's summary for the root index, as site.json."""
    return json.dumps(fields, indent=2).encode() + b"\n"


def build_root(summaries: list[dict], today: date) -> dict[str, bytes]:
    """The bucket root: index of every site, sitemap index, robots.txt and the
    error page. `summaries` are the sites' site.json contents. No I/O."""
    sites = sorted(
        (
            summary | {"valid_through": through and date.fromisoformat(through)}
            for summary in summaries
            for through in [summary.get("valid_through")]
        ),
        key=lambda summary: summary["title"].casefold(),
    )
    common = {
        "site_title": "sites.gtfs.zone",
        "base_url": f"{BASE_URL}/",
        "generated": today,
        "brand": None,
        "version": version("cape-flier"),
    }
    return {
        "index.html": render("root.html", **common, sites=sites, root=""),
        "error.html": render("error.html", **common, root="/"),
        "style.css": asset("style.css"),
        "logo.svg": asset("logo.svg"),
        "sitemap.xml": render(
            "sitemap-index.xml",
            sitemaps=[f"{BASE_URL}/{s['slug']}/sitemap.xml" for s in sites],
            generated=today,
        ),
        "robots.txt": (
            f"User-agent: *\nAllow: /\nSitemap: {BASE_URL}/sitemap.xml\n"
        ).encode(),
    }
