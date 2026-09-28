"""geometry-car's logical feeds (data.gtfs.zone/feeds.json) to resolved sites.

A site's slug is its public URL, so once assigned it is pinned in a
{feed id: slug} map kept alongside the sites and never changed or reused.
"""

import hashlib
import re
import unicodedata
from typing import Any

from cape_flier.config import CatalogFeed, Config, Site, parse_feeds

SHARDS = 16
# Root paths a site slug may not take.
RESERVED = {"countries", "sitemaps"}


def slugify(name: str) -> str:
    """ASCII, lowercase, hyphenated, as geometry_car.pages.slugify."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    return slug[:60].rstrip("-") or "feed"


def base_slug(feed: CatalogFeed) -> str:
    """The feed name's slug, or the feed id when the name has no ASCII left."""
    slug = slugify(feed.name)
    return feed.feed_id if slug == "feed" or slug in RESERVED else slug


def assign_slugs(
    feeds: list[CatalogFeed], pinned: dict[str, str], taken: set[str]
) -> dict[str, str]:
    """Pinned plus a new slug for each unpinned feed, suffixed -2, -3, ... past
    any slug pinned (even to a feed no longer listed) or in `taken`."""
    slugs = dict(pinned)
    used = set(pinned.values()) | taken
    for feed in sorted(feeds, key=lambda f: f.feed_id):
        if feed.feed_id in slugs:
            continue
        base = slug = base_slug(feed)
        n = 1
        while slug in used:
            n += 1
            slug = f"{base}-{n}"
        slugs[feed.feed_id] = slug
        used.add(slug)
    return slugs


def selected(config: Config, feed: CatalogFeed) -> bool:
    """Whether the catalog filter takes this feed."""
    rules = config.catalog
    if rules is None or feed.feed_id in rules.exclude:
        return False
    if feed.role_state.get("scheduled") != "up" or not feed.urls.get("scheduled"):
        return False
    if rules.countries and feed.country_code not in rules.countries:
        return False
    return not (
        rules.max_bytes is not None
        and feed.static_bytes is not None
        and feed.static_bytes > rules.max_bytes
    )


def resolve_sites(
    config: Config, feeds_doc: dict[str, Any], pinned: dict[str, str]
) -> tuple[list[Site], dict[str, str]]:
    """Every configured site plus every catalog feed the filter takes, and the
    updated {feed id: slug} map. A `sites:` entry for a catalog feed sets its
    options and, when given, its slug."""
    feeds = parse_feeds(feeds_doc)
    entries = {entry.feed: entry for entry in config.sites if entry.feed}
    auto = [
        feed
        for feed in feeds.values()
        if feed.feed_id not in entries and selected(config, feed)
    ]
    unslugged = [
        feeds.get(entry.feed) or CatalogFeed(feedId=entry.feed, name=entry.feed)
        for entry in entries.values()
        if not entry.slug
    ]
    fixed = {entry.slug for entry in config.sites if entry.slug}
    slugs = assign_slugs(auto + unslugged, pinned, fixed)

    sites = []
    for entry in config.sites:
        slug = entry.slug or slugs[entry.feed]
        sites.append(entry.resolve(slug, feeds.get(entry.feed)))
    defaults = config.defaults.model_dump()
    for feed in auto:
        slug = slugs[feed.feed_id]
        sites.append(Site(**defaults, slug=slug, feed=feed.feed_id, catalog=feed))

    counts: dict[str, int] = {}
    for site in sites:
        counts[site.slug] = counts.get(site.slug, 0) + 1
    clash = sorted(slug for slug, n in counts.items() if n > 1)
    if clash:
        raise ValueError(f"slugs taken twice: {', '.join(clash)}")
    return sites, slugs


def shard_of(slug: str, shards: int = SHARDS) -> int:
    """A stable shard for the slug."""
    return int.from_bytes(hashlib.sha256(slug.encode()).digest()[:4]) % shards
