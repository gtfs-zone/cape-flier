# Cape Flier: Claude Guide

## Project Overview

Generates a static timetable website per agency from GTFS, for the feeds listed
in `sites.yaml` plus the geometry-car catalog feeds its `catalog:` filter takes,
served from a Garage website bucket at `sites.gtfs.zone/<slug>/`.

## Commands

```bash
uv sync --all-extras                           # install dependencies, pipeline included
ruff check .                                   # lint
ruff format .                                  # format
uv run pytest                                  # tests
uv run cape-flier dev [--site <slug>] [--refresh]   # build listed sites + root, serve, rebuild on changes; feeds cached in .cache/feeds/
uv run cape-flier build [--site <slug>] [--zip <path>] [--cache <dir>] [--out dist/] [--listed] [--country CC] [--limit N] [--workers N]
uv run cape-flier dump --site <slug> [--zip <path>] [--date YYYY-MM-DD] [--all-stops]
uv run cape-flier serve                        # serve dist/ on the LAN
uv run cape-flier sizes                        # largest built pages vs the 50 KB gzip budget
uv run dagster dev -m cape_flier.pipeline.definitions   # pipeline UI (needs S3_* env)
pnpm install && pnpm run build:css             # rebuild templates/style.css after template changes
pre-commit install                             # install git hooks
uv run cz bump                                 # bump version, update CHANGELOG.md, tag (main only)
```

## Releasing

`uv run cz bump` on main, then push commits and tags to **both** remotes:
`git push origin main --follow-tags && git push github main --follow-tags`. The
`v*` tag triggers `.forgejo/workflows/build.yml`, which lints, tests, builds,
pushes the image and commits its digest into `deploy-gtfs-rt/gtfs`. Pushes to
main without a tag do not deploy.

## Architecture

| Module | What it does |
|---|---|
| `config.py` | Pydantic models for `sites.yaml` and a feeds.json entry (`CatalogFeed`); defaults merged into each site |
| `catalog.py` | feeds.json plus `sites.yaml` to resolved sites: catalog filter, pinned slugs, shard per slug |
| `pool.py` | Runs a function per item in memory-capped worker processes, one process per item |
| `gtfs/reader.py` | GTFS zip to typed rows, streaming, only needed columns |
| `gtfs/service.py` | Calendars to day types (Weekday / Saturday / Sunday / exceptions) |
| `timetable.py` | Route + direction + day type to a `Timetable`, plus a text dump; stop order is interlocking's topological sort, falling back to an LCS fold on cycles |
| `strip.py` | Stop-column rail lanes, endpoints and minority stops, ported from interlocking's `route-graph.ts` / `route-strip.ts` |
| `colors.py` | Hashed color for a route without `route_color`, a hex-exact port of interlocking's `route-colors.ts` |
| `build.py` | `build_site(zip_bytes, site) -> {path: bytes}`, the only entry point |
| `maps/svg.py` | Route and system maps as inline SVG: Web Mercator, Douglas-Peucker, label placement (none on bus-only system maps), basemap tiles |
| `render.py` | Jinja environment over `templates/` |
| `templates/` | Page templates and CSS (Tailwind + daisyUI, `style.css` built by `pnpm run build:css` and committed) |
| `tests/fixtures/<name>/` | Synthetic GTFS feeds as text files, zipped by `fixture_zip` |
| `cli.py` | `cape-flier build`, `dump`, `sizes`, `serve` and `dev`; downloads and writes files locally, with the root pages built as in the bucket |
| `pipeline/` | Dagster code location (a partition per shard of sites) in geometry-car's instance: download, build and upload changed files per site in workers, shard file, rewrite the root, Gatus heartbeat |

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
| geometry-car | Feed catalog pipeline; publishes `feeds.json` at data.gtfs.zone | https://git.kcfam.us/gtfs.zone/geometry-car |
| globe-of-contents | Feed catalog frontend at list.gtfs.zone | https://git.kcfam.us/gtfs.zone/globe-of-contents |
| railroad-club | Shared Python library, including the object-store client | https://git.kcfam.us/gtfs.zone/railroad-club |
| deploy-gtfs-rt | ArgoCD-managed k3s deployment | https://git.kcfam.us/gtfs.zone/deploy-gtfs-rt |
