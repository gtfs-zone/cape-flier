"""cape-flier build | serve."""

import argparse
import contextlib
import functools
import json
import logging
import socket
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cape_flier.build import build_site
from cape_flier.config import Site, load_config

log = logging.getLogger(__name__)

FEEDS_URL = "https://data.gtfs.zone/feeds.json"
USER_AGENT = "cape-flier (+https://sites.gtfs.zone)"


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
