# Cape Flier

Static timetable websites generated from GTFS, served at
[sites.gtfs.zone](https://sites.gtfs.zone). One site per agency in
`sites.yaml`: an index of routes, printed-style timetables per route, direction
and service day, and a simple route map. Plain HTML and CSS, no JavaScript
needed to read a timetable.

## Running Locally

```bash
uv sync
uv run cape-flier dev                                   # build every site and the home page, serve, rebuild on changes
uv run cape-flier dev --site columbia-county            # the same, one site only (faster rebuilds)
uv run cape-flier dev --refresh                         # download the feeds again instead of using .cache/feeds/
uv run cape-flier build                                 # clear dist/, build every site and the home page
uv run cape-flier build --site columbia-county         # rebuild dist/columbia-county/ and the home page
uv run cape-flier build --site columbia-county --zip feed.zip   # use a local zip
uv run cape-flier serve                                 # serve dist/ on the LAN, port 8000
uv run cape-flier sizes                                 # largest built pages, gzip and raw
```

`build` resolves a site's `feed:` id to its download URL through
`data.gtfs.zone/feeds.json` at build time, or uses the site's `url:` directly.

## Configuration

`sites.yaml` holds `defaults` and a list of `sites`. Each site needs a `slug`
and exactly one of `feed` or `url`, and may override any default:

| Option | Values | Default |
|---|---|---|
| `map` | `svg`, `png`, `none` | `svg` |
| `horizon_days` | days used to derive day types | `28` |
| `time_format` | `12h`, `24h` | `12h` |
| `timepoints` | `auto`, `all`, `timepoint-flag` | `auto` |
| `brand_color` | `RRGGBB` for the header and links | none |
| `basemap` | `none`, a Stadia style, or `{light: <style>, dark: <style>}` to follow the color scheme (tiles under the svg map) | `none` |

Stadia styles: `stadia-alidade-smooth`, `stadia-alidade-smooth-dark`,
`stadia-alidade-bright`, `stadia-alidade-satellite`, `stadia-outdoors`,
`stadia-osm-bright`, `stadia-toner`, `stadia-toner-lite`, `stadia-toner-dark`,
`stadia-toner-blacklite`, `stadia-toner-background`, `stadia-terrain`,
`stadia-terrain-background`, `stadia-watercolor`.

`title` names the site, and `routes` filters routes by `route_types`,
`route_ids`, `exclude_route_types` and `exclude_route_ids`. Unknown keys are an
error.

## Library

`cape_flier.build.build_site(zip_bytes, site)` returns `{path: bytes}` for one
site and does no I/O, so it can run anywhere Python does.

## Pipeline

`cape_flier.pipeline.definitions` is a Dagster code location with one partition
per site. A daily schedule at 11:00 UTC runs every site: download the feed,
build it, upload the files whose hash changed to the `sites.gtfs.zone` bucket,
delete ones no longer built, write `<slug>/manifest.json`, then rewrite the
bucket root (index, sitemap index, `robots.txt`, `error.html`). A Gatus
heartbeat is pushed once every site has been built that day.

```bash
uv sync --extra pipeline
S3_ENDPOINT=... S3_ACCESS_KEY=... S3_SECRET_KEY=... uv run dagster dev -m cape_flier.pipeline.definitions
```

Environment: `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET`
(default `sites.gtfs.zone`), `S3_REGION` (default `garage`), `GATUS_URL`,
`GATUS_TOKEN`, `CAPE_FLIER_CONFIG` (default `sites.yaml`).

## License

AGPL-3.0-or-later. See `LICENSE.txt`.
