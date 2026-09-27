# Cape Flier: Claude Guide

## Project Overview

Generates a static timetable website per agency from GTFS, for a hand-picked
list of feeds in `sites.yaml`, served from a Garage website bucket at
`sites.gtfs.zone/<slug>/`.

## Commands

```bash
uv sync                                        # install dependencies
ruff check .                                   # lint
ruff format .                                  # format
uv run pytest                                  # tests
uv run cape-flier build --site <slug> [--zip <path>] [--out dist/]
uv run cape-flier serve                        # serve dist/ on the LAN
pre-commit install                             # install git hooks
```

## Architecture

| Module | What it does |
|---|---|
| `config.py` | Pydantic models for `sites.yaml`; defaults merged into each site |
| `build.py` | `build_site(zip_bytes, site) -> {path: bytes}`, the only entry point |
| `render.py` | Jinja environment over `styles/`, falling back to `classic` templates |
| `styles/<style>/` | Templates and CSS per style |
| `cli.py` | `cape-flier build` and `serve`; the only place that downloads or writes files |

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
