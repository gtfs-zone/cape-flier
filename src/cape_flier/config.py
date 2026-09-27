"""Pydantic models for sites.yaml: defaults plus per-site overrides."""

from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

Style = Literal["classic", "rail"]
MapKind = Literal["svg", "png", "none"]
TimeFormat = Literal["12h", "24h"]
Orientation = Literal["stops-down", "trips-down"]
Timepoints = Literal["auto", "all", "timepoint-flag"]

SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Options(Strict):
    style: Style = "classic"
    map: MapKind = "svg"
    horizon_days: int = Field(28, gt=0, le=366)
    time_format: TimeFormat = "12h"
    orientation: Orientation = "stops-down"
    timepoints: Timepoints = "auto"


class RouteFilter(Strict):
    """Include by route_type or route_id (empty means all), then exclude."""

    route_types: tuple[int, ...] = ()
    route_ids: tuple[str, ...] = ()
    exclude_route_types: tuple[int, ...] = ()
    exclude_route_ids: tuple[str, ...] = ()

    def accepts(self, route_id: str, route_type: int) -> bool:
        if self.route_types and route_type not in self.route_types:
            return False
        if self.route_ids and route_id not in self.route_ids:
            return False
        return (
            route_type not in self.exclude_route_types
            and route_id not in self.exclude_route_ids
        )


class Site(Options):
    """One site with its options fully resolved against the defaults."""

    slug: str = Field(pattern=SLUG_PATTERN)
    feed: str | None = Field(None, pattern=r"^f-[0-9a-f]{10}$")
    url: str | None = None
    title: str | None = None
    routes: RouteFilter = RouteFilter()

    @model_validator(mode="after")
    def one_source(self) -> Self:
        if (self.feed is None) == (self.url is None):
            raise ValueError(f"site {self.slug!r} needs exactly one of feed or url")
        return self

    def download_url(self, feeds_doc: dict[str, Any]) -> str:
        """The scheduled GTFS URL, looking a feed id up in feeds.json."""
        if self.url is not None:
            return self.url
        for entry in feeds_doc.get("feeds", []):
            if entry.get("feedId") == self.feed:
                urls = entry.get("urls", {}).get("scheduled", [])
                if urls:
                    return urls[0]
                raise LookupError(f"feed {self.feed} has no scheduled URL")
        raise LookupError(f"feed {self.feed} not in feeds.json")


class Config(Strict):
    defaults: Options = Options()
    sites: tuple[Site, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def apply_defaults(cls, data: object) -> object:
        """Fill each site's unset options from `defaults`."""
        if not isinstance(data, dict):
            return data
        defaults = data.get("defaults") or {}
        if not isinstance(defaults, dict):
            return data
        sites = data.get("sites") or []
        merged = [defaults | site if isinstance(site, dict) else site for site in sites]
        return data | {"sites": merged}

    @model_validator(mode="after")
    def unique_slugs(self) -> Self:
        slugs = [site.slug for site in self.sites]
        dupes = sorted({slug for slug in slugs if slugs.count(slug) > 1})
        if dupes:
            raise ValueError(f"duplicate site slugs: {', '.join(dupes)}")
        return self

    def site(self, slug: str) -> Site:
        for site in self.sites:
            if site.slug == slug:
                return site
        raise KeyError(f"no site {slug!r} in config")


def load_config(text: str) -> Config:
    return Config.model_validate(yaml.safe_load(text) or {})
