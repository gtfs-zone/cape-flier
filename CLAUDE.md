# gtfs-zone-timetable-sites: Claude Guide

## Project Overview

Generates a static timetable website per agency from GTFS, for the feeds listed
in `sites.yaml` plus the feed-catalog catalog feeds its `catalog:` filter takes,
served from a Garage website bucket at `sites.gtfs.zone/<slug>/`.

## Commands

```bash
uv sync --all-extras                           # install dependencies, pipeline included
ruff check .                                   # lint
ruff format .                                  # format
uv run pytest                                  # tests
uv run timetable-sites dev [--site <slug>] [--refresh]   # build sites.yaml's dev: feeds + root, serve, rebuild on changes; feeds cached in .cache/feeds/
uv run timetable-sites build [--site <slug>] [--zip <path>] [--cache <dir>] [--out dist/] [--listed] [--dev] [--country CC] [--limit N] [--workers N]
uv run timetable-sites dump --site <slug> [--zip <path>] [--date YYYY-MM-DD] [--all-stops]
uv run timetable-sites serve                        # serve dist/ on the LAN
uv run timetable-sites sizes                        # largest built pages by gzip size
uv run dagster dev -m gtfs_zone_timetable_sites.pipeline.definitions   # pipeline UI (needs S3_* env)
pnpm install && pnpm run build:css             # rebuild templates/style.css after template changes
pre-commit install                             # install git hooks
uv run cz bump                                 # bump version, update CHANGELOG.md, tag (main only)
```

## Releasing

`uv run cz bump` on main, then `git push origin main --follow-tags`. The `v*`
tag triggers `.github/workflows/build.yml`, which lints, tests, builds, pushes
the image to ghcr.io and commits its digest into `gtfs-zone-infra/gtfs`. Pushes to
main without a tag do not deploy.

## Architecture

| Module | What it does |
|---|---|
| `config.py` | Pydantic models for `sites.yaml` and a feeds.json entry (`CatalogFeed`); defaults merged into each site |
| `catalog.py` | feeds.json plus `sites.yaml` to resolved sites: catalog filter, pinned slugs, shard per slug |
| `pool.py` | Runs a function per item in memory-capped worker processes, one process per item |
| `gtfs/reader.py` | GTFS zip to typed rows, streaming, only needed columns |
| `gtfs/service.py` | Calendars to day types (Weekday / Saturday / Sunday / exceptions) |
| `timetable.py` | Route + direction + day type to a `Timetable`, plus a text dump; stop order is gtfs-zone-web-common's topological sort, falling back to an LCS fold on cycles |
| `strip.py` | Stop-column rail lanes, endpoints and minority stops, ported from gtfs-zone-web-common's `route-graph.ts` / `route-strip.ts` |
| `colors.py` | Hashed color for a route without `route_color`, a hex-exact port of gtfs-zone-web-common's `route-colors.ts` |
| `build.py` | `build_site(zip_bytes, site) -> {path: bytes}`, the only entry point |
| `facts.py` | What a parsed zip contains (feed_info, service range, agencies, counts) for the content report |
| `maps/svg.py` | Route and system maps as inline SVG: Web Mercator, Douglas-Peucker, label placement (none on bus-only system maps), basemap tiles |
| `maps/split.py` | A mode's routes to system maps by grid density: local clusters, then long routes grouped by overlap with the rest sharing one map; one map when that fragments the mode |
| `render.py` | Jinja environment over `templates/` |
| `templates/` | Page templates and CSS (Tailwind + daisyUI, `style.css` built by `pnpm run build:css` and committed) |
| `tests/fixtures/<name>/` | Synthetic GTFS feeds as text files, zipped by `fixture_zip` |
| `cli.py` | `timetable-sites build`, `dump`, `sizes`, `serve` and `dev`; downloads and writes files locally, with the root pages built as in the bucket |
| `pipeline/` | Dagster code location (a partition per shard of sites) in feed-catalog's instance: download, build and upload changed files per site in workers, shard file and content report, skip known-bad feeds, rewrite the root, Gatus heartbeat |

## Rules

- Never include `Co-Authored-By: Claude ...` trailers in commit messages.
- The core is pure: nothing outside `cli.py` and `pipeline/` does network or
  disk I/O, so `build_site` can later run in Pyodide or on the fly.
- No Playwright or other browser automation; pages are checked by hand on a
  phone and a desktop.
- Module loggers are named `log`, never `logger`: `log = logging.getLogger(__name__)`
- Cross-repo work is allowed: sibling gtfs.zone repos live under the same parent
  directory and may be read and edited when a change spans repos.

## Related Repos

| Repo | Description | URL |
|---|---|---|
| feed-catalog | Feed catalog pipeline; publishes `feeds.json` at data.gtfs.zone | https://github.com/gtfs-zone/gtfs-zone-feed-catalog |
| feed-list | Feed catalog frontend at list.gtfs.zone | https://github.com/gtfs-zone/gtfs-zone-feed-list |
| gtfs-zone-db-models | Shared Python library, including the object-store client | https://github.com/gtfs-zone/gtfs-zone-db-models |
| gtfs-zone-infra | ArgoCD-managed k3s deployment | https://github.com/gtfs-zone/gtfs-zone-infra |
