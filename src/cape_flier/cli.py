"""cape-flier build | dump | sizes | serve | dev."""

import argparse
import contextlib
import functools
import gzip
import json
import logging
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import date
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cape_flier.build import build_root, build_site, site_feed, site_timetables
from cape_flier.config import FEEDS_URL, USER_AGENT, Site, load_config
from cape_flier.timetable import to_text

log = logging.getLogger(__name__)


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def feed_zip(site: Site, zip_path: Path | None, cache: Path | None = None) -> bytes:
    """The local zip when given, else the cached download in `cache`, else a
    download of the site's feed (saved to `cache` when given)."""
    if zip_path is not None:
        return zip_path.read_bytes()
    cached = cache / f"{site.slug}.zip" if cache else None
    if cached and cached.exists():
        return cached.read_bytes()
    feeds_doc = json.loads(fetch(FEEDS_URL)) if site.feed else {}
    url = site.download_url(feeds_doc)
    log.info("downloading %s", url)
    body = fetch(url)
    if cached:
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(body)
    return body


def write_files(files: dict[str, bytes], root: Path) -> None:
    for path, body in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)


def clear(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def write_root(out: Path) -> None:
    """The bucket root pages from every built site's site.json under `out`,
    with each site's pages dated by its build."""
    summaries = [json.loads(p.read_text()) for p in sorted(out.glob("*/site.json"))]
    pages = {
        summary["slug"]: {
            page.relative_to(out / summary["slug"]).as_posix(): summary["generated"]
            for page in (out / summary["slug"]).rglob("index.html")
        }
        for summary in summaries
    }
    write_files(build_root(summaries, date.today(), pages), out)


def build(args: argparse.Namespace) -> None:
    """Build one site, or every site, into a cleared `out`, then the root."""
    config = load_config(args.config.read_text())
    if args.zip and not args.site:
        raise SystemExit("--zip needs --site")
    sites = [config.site(args.site)] if args.site else config.sites
    if not args.site:
        clear(args.out)
    for site in sites:
        files = build_site(feed_zip(site, args.zip, args.cache), site)
        root = args.out / site.slug
        clear(root)
        write_files(files, root)
        log.info("wrote %d files to %s", len(files), root)
    write_root(args.out)


def dump(args: argparse.Namespace) -> None:
    site = load_config(args.config.read_text()).site(args.site)
    feed = site_feed(feed_zip(site, args.zip), site)
    today = args.date or date.today()
    for route, tables in site_timetables(feed, site, today):
        print(f"# {route.name}")
        for table in tables:
            print(to_text(table, site.time_format, all_rows=args.all_stops))
            print()


BUDGET_GZIP = 50_000


def sizes(args: argparse.Namespace) -> None:
    """Print the largest built pages by gzip size, flagging those over budget."""
    rows = []
    for path in args.dir.rglob("*.html"):
        body = path.read_bytes()
        rows.append((len(gzip.compress(body)), len(body), path))
    rows.sort(reverse=True)
    for packed, raw, path in rows[: args.top]:
        flag = "  OVER" if packed > BUDGET_GZIP else ""
        print(f"{packed / 1000:6.1f} {raw / 1000:7.1f} KB  {path}{flag}")


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_error(
        self, code: int, message: str | None = None, explain: str | None = None
    ) -> None:
        """Serve error.html for a 404, as the bucket does."""
        page = Path(self.directory) / "error.html"
        if code != 404 or not page.exists():
            return super().send_error(code, message, explain)
        body = page.read_bytes()
        self.send_response(404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


def lan_address() -> str:
    """This machine's address on the default route, for opening on a phone."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("192.0.2.1", 80))
            return probe.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def server(args: argparse.Namespace) -> ThreadingHTTPServer:
    handler = functools.partial(Handler, directory=str(args.dir))
    httpd = ThreadingHTTPServer((args.host, args.port), handler)
    host = lan_address() if args.host == "0.0.0.0" else args.host
    log.info("serving %s at http://%s:%d/", args.dir, host, args.port)
    return httpd


def serve(args: argparse.Namespace) -> None:
    with server(args) as httpd, contextlib.suppress(KeyboardInterrupt):
        httpd.serve_forever()


PACKAGE = Path(__file__).parent
REPO = PACKAGE.parent.parent
CSS_SOURCES = (".html", "input.css")


def snapshot(paths: list[Path]) -> dict[Path, float]:
    """Modification times of every file under `paths`."""
    files = [f for p in paths for f in ([p] if p.is_file() else p.rglob("*"))]
    return {
        f: f.stat().st_mtime
        for f in files
        if f.is_file() and "__pycache__" not in f.parts
    }


def dev(args: argparse.Namespace) -> None:
    """Build every site into a cleared dir, serve it, and rebuild on changes to
    the package or config. Feeds are kept in `--cache` across runs; `--refresh`
    downloads them again."""
    watched = [PACKAGE, args.config]
    if args.refresh:
        clear(args.cache)
    cache = str(args.cache)
    with server(args) as httpd:
        command = [
            sys.executable,
            "-m",
            "cape_flier.cli",
            "build",
            "--out",
            str(args.dir),
        ]
        command += ["--config", str(args.config), "--cache", cache]
        command += ["--site", args.site] if args.site else []

        def rebuild(changed: set[Path]) -> None:
            if any(p.name.endswith(CSS_SOURCES) for p in changed):
                subprocess.run(["pnpm", "run", "--silent", "build:css"], cwd=REPO)
            if subprocess.run(command).returncode == 0:
                log.info("built, refresh the page")

        rebuild(set())
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        seen = snapshot(watched)
        with contextlib.suppress(KeyboardInterrupt):
            while True:
                time.sleep(0.5)
                now = snapshot(watched)
                changed = {
                    p for p in now.keys() | seen.keys() if now.get(p) != seen.get(p)
                }
                if changed:
                    log.info("changed: %s", ", ".join(sorted(p.name for p in changed)))
                    rebuild(changed)
                    # The css build writes style.css; take it in without another build.
                    now = snapshot(watched)
                seen = now


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="cape-flier")
    commands = root.add_subparsers(dest="command", required=True)

    build_cmd = commands.add_parser("build", help="build sites and the root")
    build_cmd.add_argument("--site", help="site slug in the config (default all)")
    build_cmd.add_argument(
        "--zip", type=Path, help="local GTFS zip instead of the feed"
    )
    build_cmd.add_argument(
        "--cache", type=Path, help="dir to keep downloaded feeds in and reuse"
    )
    build_cmd.add_argument("--out", type=Path, default=Path("dist"))
    build_cmd.add_argument("--config", type=Path, default=Path("sites.yaml"))
    build_cmd.set_defaults(func=build)

    dump_cmd = commands.add_parser("dump", help="print one site's timetables")
    dump_cmd.add_argument("--site", required=True, help="site slug in the config")
    dump_cmd.add_argument("--zip", type=Path, help="local GTFS zip instead of the feed")
    dump_cmd.add_argument("--config", type=Path, default=Path("sites.yaml"))
    dump_cmd.add_argument(
        "--date", type=date.fromisoformat, help="horizon start (default today)"
    )
    dump_cmd.add_argument(
        "--all-stops", action="store_true", help="include non-timepoint stops"
    )
    dump_cmd.set_defaults(func=dump)

    sizes_cmd = commands.add_parser("sizes", help="report the largest built pages")
    sizes_cmd.add_argument("--dir", type=Path, default=Path("dist"))
    sizes_cmd.add_argument("--top", type=int, default=10)
    sizes_cmd.set_defaults(func=sizes)

    serve_cmd = commands.add_parser("serve", help="serve built sites")
    serve_cmd.add_argument("--dir", type=Path, default=Path("dist"))
    serve_cmd.add_argument("--host", default="0.0.0.0")
    serve_cmd.add_argument("--port", type=int, default=8000)
    serve_cmd.set_defaults(func=serve)

    dev_cmd = commands.add_parser(
        "dev", help="build every site, serve, and rebuild on changes"
    )
    dev_cmd.add_argument("--site", help="build only this site")
    dev_cmd.add_argument(
        "--cache", type=Path, default=Path(".cache/feeds"), help="downloaded feeds"
    )
    dev_cmd.add_argument(
        "--refresh", action="store_true", help="download every feed again"
    )
    dev_cmd.add_argument("--dir", type=Path, default=Path("dist"))
    dev_cmd.add_argument("--config", type=Path, default=Path("sites.yaml"))
    dev_cmd.add_argument("--host", default="0.0.0.0")
    dev_cmd.add_argument("--port", type=int, default=8000)
    dev_cmd.set_defaults(func=dev)

    return root


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
