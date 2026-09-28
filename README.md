# Cape Flier

Static timetable websites generated from GTFS, served at
[sites.gtfs.zone](https://sites.gtfs.zone). One site per agency in
`sites.yaml`: an index of routes, printed-style timetables per route, direction
and service day, and a simple route map. Plain HTML and CSS, no JavaScript
needed to read a timetable.

## Running Locally

```bash
uv sync
uv run cape-flier build --site columbia-county         # download the feed, write dist/columbia-county/
uv run cape-flier build --site columbia-county --zip feed.zip   # use a local zip
uv run cape-flier serve                                 # serve dist/ on the LAN, port 8000
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
| `basemap` | `none`, `stadia-toner` (tiles under the svg map) | `none` |

`title` names the site, and `routes` filters routes by `route_types`,
`route_ids`, `exclude_route_types` and `exclude_route_ids`. Unknown keys are an
error.

## Library

`cape_flier.build.build_site(zip_bytes, site)` returns `{path: bytes}` for one
site and does no I/O, so it can run anywhere Python does.

## License

AGPL-3.0-or-later. See `LICENSE.txt`.
