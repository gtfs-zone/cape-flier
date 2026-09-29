"""build_site: the only entry point from a GTFS zip to a site's files."""

import hashlib
import io
import json
import re
import zipfile
from datetime import date
from importlib.metadata import version

from cape_flier.catalog import shard_of
from cape_flier.config import RouteFilter, Site
from cape_flier.facts import feed_facts
from cape_flier.gtfs.reader import Agency, Feed, Route, read_feed
from cape_flier.gtfs.service import day_types, horizon_start
from cape_flier.maps.svg import route_map, system_map
from cape_flier.pages import (
    breadcrumbs,
    day_views,
    feed_amenities,
    mode_groups,
    modes_label,
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
ROOT_TITLE = "sites.gtfs.zone"
# The footer's build date, as base.html marks it up.
GENERATED = re.compile(rb'<time class="generated"[^>]*>.*?</time>')


def page_digest(body: bytes) -> str:
    """sha256 of a page without its build date, so it changes only with the
    page's content."""
    return hashlib.sha256(GENERATED.sub(b"", body)).hexdigest()


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


def agencies_by_routes(feed: Feed) -> list[Agency]:
    """The feed's agencies, those running the most routes first."""
    counts: dict[str, int] = {}
    for route in feed.routes.values():
        counts[route.agency_id] = counts.get(route.agency_id, 0) + 1
    return sorted(feed.agencies.values(), key=lambda a: -counts.get(a.agency_id, 0))


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
    agencies = agencies_by_routes(feed)
    base_url = f"{BASE_URL}/{site.slug}/"
    feed_notes, marked = feed_amenities(
        [table for _, tables in timetables for table in tables]
    )
    common = {
        "site_title": site.title or (tidy(agencies[0].name) if agencies else site.slug),
        "base_url": base_url,
        "generated": today,
        "feed_notes": feed_notes,
        "source": data_source(feed, site),
    }

    routes = [
        route_view(route, slugs[route.route_id], tables, labels.get(route.route_id, ""))
        for route, tables in timetables
    ]
    through = valid_through(feed, today)
    maps = site.map == "svg"
    system_routes = {
        view.slug: (view.title, view.badge, view.line_color, tables, f"{view.slug}/")
        for view, (_, tables) in zip(routes, timetables, strict=True)
    }
    groups = mode_groups(routes)
    # One system map per mode, headed when there is more than one.
    home_maps = [
        (group.heading if len(groups) > 1 else "", svg)
        for group in (groups if maps else [])
        for svg in [
            system_map(
                feed,
                f"{common['site_title']} {group.mode}",
                [system_routes[view.slug] for view in group.routes],
                site.basemap,
            )
        ]
        if svg
    ]
    trail = [(ROOT_TITLE, f"{BASE_URL}/"), (common["site_title"], base_url)]
    files = {
        "index.html": render(
            "index.html",
            **common,
            agencies=agencies,
            routes=routes,
            groups=groups,
            modes=modes_label([view.mode for view in routes]),
            maps=home_maps,
            valid_through=through,
            feed_url=f"{LIST_URL}/#feed={site.feed}" if site.feed else "",
            jsonld=breadcrumbs(trail),
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
            days=day_views(feed, tables, site.time_format, marked),
            jsonld=breadcrumbs([*trail, (view.title, f"{base_url}{view.slug}/")]),
            root="../",
        )
    files["site.json"] = summary_json(
        slug=site.slug,
        title=common["site_title"],
        routes=len(routes),
        valid_through=through.isoformat() if through else None,
        generated=today.isoformat(),
        country_code=site.catalog and site.catalog.country_code,
        country=site.catalog and site.catalog.country,
        subdivision=site.catalog and site.catalog.subdivision,
    )
    files["content.json"] = summary_json(
        **feed_facts(zip_bytes, feed, site.routes != RouteFilter())
    )
    files["style.css"] = asset("style.css")
    files["logo.svg"] = asset("logo.svg")
    return files


def data_source(feed: Feed, site: Site) -> dict[str, object]:
    """Who published the feed, where it was downloaded, its license and catalog
    pages, for the footer."""
    info = feed.feed_info
    agency = next(iter(agencies_by_routes(feed)), None)
    publisher = (info and tidy(info.publisher_name)) or (agency and tidy(agency.name))
    publisher_url = (info and info.publisher_url) or (agency and agency.url)
    try:
        download_url = site.download_url()
    except LookupError:
        download_url = ""
    return {
        "publisher": publisher or site.slug,
        "publisher_url": publisher_url or "",
        "download_url": download_url,
        "licenses": site.licenses(),
        "catalog_links": site.catalog.catalog_links if site.catalog else (),
    }


def summary_json(**fields: object) -> bytes:
    """A site's summary for the root index, as site.json."""
    return json.dumps(fields, indent=2).encode() + b"\n"


def sitemap_urls(pages: dict[str, dict[str, str]]) -> list[tuple[str, str]]:
    """(url, lastmod) for each site's pages, from {slug: {path: YYYY-MM-DD}}."""
    urls = []
    for slug in sorted(pages):
        # The site's index first, then its routes.
        for path, modified in sorted(
            pages[slug].items(), key=lambda item: (item[0] != "index.html", item[0])
        ):
            if path == "index.html" or path.endswith("/index.html"):
                urls.append(
                    (f"{BASE_URL}/{slug}/{path[: -len('index.html')]}", modified)
                )
    return urls


OTHER = "other"
# A site whose timetables end within this many days is marked as expiring.
EXPIRING_DAYS = 14


def country_key(summary: dict) -> str:
    """The lowercase country code a site is listed under."""
    return (summary.get("country_code") or OTHER).lower()


def country_groups(sites: list[dict]) -> list[dict]:
    """Countries by name, each with its sites grouped by subdivision."""
    countries: dict[str, list[dict]] = {}
    for site in sites:
        countries.setdefault(country_key(site), []).append(site)
    groups = []
    for key, members in countries.items():
        fallback = "Other" if key == OTHER else key.upper()
        subdivisions: dict[str, list[dict]] = {}
        for site in members:
            subdivisions.setdefault(site.get("subdivision") or "", []).append(site)
        groups.append(
            {
                "key": key,
                "name": members[0].get("country") or fallback,
                "sites": members,
                # Unnamed subdivisions last.
                "subdivisions": sorted(
                    subdivisions.items(), key=lambda item: (not item[0], item[0])
                ),
            }
        )
    # Other last.
    return sorted(groups, key=lambda g: (g["key"] == OTHER, g["name"].casefold()))


def site_status(summary: dict, outcome: str | None, today: date) -> str:
    """ok, warn (expiring soon, or the last update failed and an older build is
    served), bad (expired or no routes) or unknown, from a site.json summary and
    the outcome of its last download and build."""
    if "routes" not in summary:
        return "unknown"
    through = summary.get("valid_through")
    if not summary["routes"] or not through or date.fromisoformat(through) < today:
        return "bad"
    expiring = (date.fromisoformat(through) - today).days < EXPIRING_DAYS
    return "warn" if expiring or (outcome and outcome != "ok") else "ok"


def build_root(
    summaries: list[dict],
    today: date,
    pages: dict[str, dict[str, str]] | None = None,
    indexnow_key: str | None = None,
    outcomes: dict[str, str] | None = None,
) -> dict[str, bytes]:
    """The bucket root: an index of countries, a page per country listing its
    sites, a sitemap index over one sitemap per shard, robots.txt and the error
    page. `summaries` are the sites' site.json contents, `pages` each site's
    page paths with the date they last changed and `outcomes` each site's last
    download and build outcome. No I/O."""
    outcomes = outcomes or {}
    sites = sorted(
        (
            summary
            | {
                "valid_through": through and date.fromisoformat(through),
                "status": site_status(summary, outcomes.get(summary["slug"]), today),
            }
            for summary in summaries
            for through in [summary.get("valid_through")]
        ),
        key=lambda summary: summary["title"].casefold(),
    )
    countries = country_groups(sites)
    common = {
        "site_title": ROOT_TITLE,
        "base_url": f"{BASE_URL}/",
        "generated": today,
        "version": version("cape-flier"),
    }
    website = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": ROOT_TITLE,
        "url": f"{BASE_URL}/",
    }
    files = {
        "index.html": render(
            "root.html",
            **common,
            countries=countries,
            total=len(sites),
            jsonld=website,
            root="",
        ),
        "error.html": render("error.html", **common, root="/"),
        "style.css": asset("style.css"),
        "logo.svg": asset("logo.svg"),
    }
    for country in countries:
        url = f"{BASE_URL}/countries/{country['key']}/"
        files[f"countries/{country['key']}/index.html"] = render(
            "country.html",
            **(common | {"base_url": url}),
            country=country,
            jsonld=breadcrumbs([(ROOT_TITLE, f"{BASE_URL}/"), (country["name"], url)]),
            root="../../",
        )

    # One sitemap per shard of sites, so each stays far below 50,000 URLs.
    root_urls = [(f"{BASE_URL}/", None)] + [
        (f"{BASE_URL}/countries/{country['key']}/", None) for country in countries
    ]
    maps = {"sitemaps/root.xml": root_urls}
    shards: dict[int, dict[str, dict[str, str]]] = {}
    for slug, site_pages in (pages or {}).items():
        shards.setdefault(shard_of(slug), {})[slug] = site_pages
    for shard, shard_pages in sorted(shards.items()):
        maps[f"sitemaps/{shard:02d}.xml"] = sitemap_urls(shard_pages)
    for path, urls in maps.items():
        files[path] = render("sitemap.xml", urls=urls)
    files["sitemap.xml"] = render(
        "sitemap-index.xml",
        sitemaps=[
            (f"{BASE_URL}/{path}", max((m for _, m in urls if m), default=None))
            for path, urls in maps.items()
        ],
    )
    files["robots.txt"] = (
        f"User-agent: *\nAllow: /\nSitemap: {BASE_URL}/sitemap.xml\n"
    ).encode()
    if indexnow_key:
        files[f"{indexnow_key}.txt"] = indexnow_key.encode()
    return files
