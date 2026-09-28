"""cape-flier build | serve."""

import argparse
import contextlib
import functools
import gzip
import json
import logging
import socket
import urllib.request
from datetime import date
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cape_flier.build import build_site, site_feed, site_timetables
from cape_flier.config import FEEDS_URL, USER_AGENT, Site, load_config
from cape_flier.timetable import to_text

log = logging.getLogger(__name__)


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def feed_zip(site: Site, zip_path: Path | None) -> bytes:
    """The local zip when given, else a download of the site's feed."""
    if zip_path is not None:
        return zip_path.read_bytes()
    feeds_doc = json.loads(fetch(FEEDS_URL)) if site.feed else {}
    url = site.download_url(feeds_doc)
    log.info("downloading %s", url)
    return fetch(url)


def write_files(files: dict[str, bytes], root: Path) -> None:
    for path, body in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)


def build(args: argparse.Namespace) -> None:
    site = load_config(args.config.read_text()).site(args.site)
    files = build_site(feed_zip(site, args.zip), site)
    root = args.out / site.slug
    write_files(files, root)
    log.info("wrote %d files to %s", len(files), root)


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


def lan_address() -> str:
    """This machine's address on the default route, for opening on a phone."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("192.0.2.1", 80))
            return probe.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def serve(args: argparse.Namespace) -> None:
    handler = functools.partial(Handler, directory=str(args.dir))
    with ThreadingHTTPServer((args.host, args.port), handler) as server:
        host = lan_address() if args.host == "0.0.0.0" else args.host
        log.info("serving %s at http://%s:%d/", args.dir, host, args.port)
        with contextlib.suppress(KeyboardInterrupt):
            server.serve_forever()


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="cape-flier")
    commands = root.add_subparsers(dest="command", required=True)

    build_cmd = commands.add_parser("build", help="build one site")
    build_cmd.add_argument("--site", required=True, help="site slug in the config")
    build_cmd.add_argument(
        "--zip", type=Path, help="local GTFS zip instead of the feed"
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

    return root


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parser().parse_args(argv)
    args.func(args)
