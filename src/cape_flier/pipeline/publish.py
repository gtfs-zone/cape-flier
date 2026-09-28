"""Download a feed and publish built files to the bucket.

Each site lives under `<slug>/` with a `manifest.json` written last, holding
the build date, the cape-flier version, the feed's source headers and a hash
per file, so a rebuild uploads only what changed.
"""

import hashlib
import json
import logging
from datetime import date
from typing import TYPE_CHECKING, Protocol

from cape_flier.build import build_root

if TYPE_CHECKING:
    import httpx

log = logging.getLogger(__name__)

MANIFEST = "manifest.json"


class Store(Protocol):
    def list_keys(self, prefix: str = "") -> set[str]: ...
    def get(self, key: str) -> bytes | None: ...
    def put(self, key: str, body: bytes) -> None: ...
    def delete(self, keys: set[str]) -> None: ...


def download(
    http: "httpx.Client", url: str, previous: dict | None
) -> tuple[bytes | None, dict]:
    """The feed zip and its source headers; None when `previous` still matches."""
    headers = {}
    if previous and previous.get("url") == url:
        if previous.get("etag"):
            headers["If-None-Match"] = previous["etag"]
        if previous.get("last_modified"):
            headers["If-Modified-Since"] = previous["last_modified"]
    response = http.get(url, headers=headers)
    if response.status_code == 304:
        return None, previous or {}
    response.raise_for_status()
    return response.content, {
        "url": url,
        "etag": response.headers.get("etag"),
        "last_modified": response.headers.get("last-modified"),
    }


def read_manifest(store: Store, slug: str) -> dict | None:
    body = store.get(f"{slug}/{MANIFEST}")
    return json.loads(body) if body else None


def publish_site(
    store: Store,
    slug: str,
    files: dict[str, bytes],
    source: dict,
    today: date,
    version: str,
) -> dict[str, int]:
    """Upload changed files, delete ones no longer built, then the manifest."""
    old = (read_manifest(store, slug) or {}).get("files", {})
    hashes = {path: hashlib.sha256(body).hexdigest() for path, body in files.items()}
    changed = [path for path in files if old.get(path) != hashes[path]]
    # Pages last, so a new page never links a stylesheet that is not up yet.
    for path in sorted(changed, key=lambda p: (p.endswith(".html"), p)):
        store.put(f"{slug}/{path}", files[path])
    built = {f"{slug}/{path}" for path in files} | {f"{slug}/{MANIFEST}"}
    stale = store.list_keys(f"{slug}/") - built
    store.delete(stale)
    manifest = {
        "built": today.isoformat(),
        "version": version,
        "source": source,
        "files": hashes,
    }
    store.put(f"{slug}/{MANIFEST}", json.dumps(manifest, indent=2).encode())
    return {"files": len(files), "uploaded": len(changed), "deleted": len(stale)}


def publish_root(store: Store, slugs: list[str], today: date) -> list[str]:
    """Rewrite the root pages from each site's site.json and delete sites no
    longer configured. Returns the slugs not built today."""
    summaries, behind = [], []
    for slug in slugs:
        summary = store.get(f"{slug}/site.json")
        if summary:
            summaries.append(json.loads(summary))
        manifest = read_manifest(store, slug)
        if not manifest or manifest.get("built") != today.isoformat():
            behind.append(slug)
    files = build_root(summaries, today)
    for path, body in files.items():
        store.put(path, body)
    dropped = {
        key
        for key in store.list_keys()
        if key not in files and key.split("/", 1)[0] not in slugs
    }
    if dropped:
        log.info("deleting %d objects of unconfigured sites", len(dropped))
        store.delete(dropped)
    return behind
