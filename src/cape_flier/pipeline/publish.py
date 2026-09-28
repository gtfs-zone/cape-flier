"""Download a feed and publish built files to the bucket.

Each site lives under `<slug>/` with a `manifest.json` written last, holding
the build date, the cape-flier version, the feed's source headers, a hash per
file, so a rebuild uploads only what changed, and per page a digest without the
build date and the date that digest last changed, for the sitemap.

Sites are built in shards. Each shard keeps `_shards/<nn>.json`, per site its
summary, build date and page dates, so the root is rewritten from the shard
files rather than from every site's manifest. `slugs.json` pins each catalog
feed's slug.
"""

import hashlib
import json
import logging
from collections.abc import Callable
from datetime import date
from typing import TYPE_CHECKING, Protocol

from cape_flier.build import build_root, build_site, page_digest
from cape_flier.config import Site
from cape_flier.pool import run_all

if TYPE_CHECKING:
    import httpx

log = logging.getLogger(__name__)

MANIFEST = "manifest.json"
SLUGS = "slugs.json"
SHARD_PREFIX = "_shards/"
# Keys at the root that are state, not pages, and never pruned.
STATE = (SLUGS, SHARD_PREFIX)
# Below this share of the sites listed so far, a catalog is taken to be broken
# and no site is deleted.
PRUNE_RATIO = 0.8


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


def read_json(store: Store, key: str) -> dict | None:
    body = store.get(key)
    return json.loads(body) if body else None


def put_json(store: Store, key: str, value: object) -> None:
    store.put(key, json.dumps(value, indent=2, sort_keys=True).encode())


def read_manifest(store: Store, slug: str) -> dict | None:
    return read_json(store, f"{slug}/{MANIFEST}")


def page_dates(
    files: dict[str, bytes], old: dict[str, dict], today: date
) -> dict[str, dict]:
    """{path: {digest, modified}} per page, keeping the old date while the
    digest is unchanged."""
    pages = {}
    for path, body in files.items():
        if not path.endswith(".html"):
            continue
        digest = page_digest(body)
        previous = old.get(path, {})
        same = previous.get("digest") == digest and previous.get("modified")
        pages[path] = {
            "digest": digest,
            "modified": previous["modified"] if same else today.isoformat(),
        }
    return pages


def publish_site(
    store: Store,
    slug: str,
    files: dict[str, bytes],
    source: dict,
    today: date,
    version: str,
) -> tuple[dict[str, int], list[str], dict[str, dict]]:
    """Upload changed files, delete ones no longer built, then the manifest.
    Returns counts, the pages whose content changed today and every page's
    digest and date."""
    previous = read_manifest(store, slug) or {}
    old = previous.get("files", {})
    old_pages = previous.get("pages", {})
    pages = page_dates(files, old_pages, today)
    changed_pages = sorted(
        path
        for path, page in pages.items()
        if old_pages.get(path, {}).get("digest") != page["digest"]
    )
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
        "pages": pages,
    }
    store.put(f"{slug}/{MANIFEST}", json.dumps(manifest, indent=2).encode())
    counts = {"files": len(files), "uploaded": len(changed), "deleted": len(stale)}
    return counts, changed_pages, pages


def site_entry(summary: dict, built: str, pages: dict[str, dict]) -> dict:
    """A site's line in its shard file."""
    return {
        "summary": summary,
        "built": built,
        "pages": {path: page["modified"] for path, page in pages.items()},
    }


def build_and_publish(
    store: Store, http: "httpx.Client", site: Site, today: date, version: str
) -> dict:
    """Download, build and publish one site. Returns its counts, the pages
    changed today and its shard entry."""
    previous = read_manifest(store, site.slug)
    # Builds depend on the date and the code, so only a second run on the same
    # day with the same version may skip.
    same_day = (
        previous
        and previous.get("built") == today.isoformat()
        and previous.get("version") == version
    )
    url = site.download_url()
    body, source = download(http, url, previous["source"] if same_day else None)
    if body is None:
        summary = read_json(store, f"{site.slug}/site.json") or {}
        return {
            "counts": {"files": len(previous["files"]), "uploaded": 0, "deleted": 0},
            "changed": [],
            "entry": site_entry(summary, previous["built"], previous["pages"]),
        }
    files = build_site(body, site, today)
    counts, changed, pages = publish_site(
        store, site.slug, files, source, today, version
    )
    summary = json.loads(files["site.json"])
    return {
        "counts": counts,
        "changed": changed,
        "entry": site_entry(summary, today.isoformat(), pages),
    }


def shard_key(shard: int) -> str:
    return f"{SHARD_PREFIX}{shard:02d}.json"


def run_shard(
    store: Store,
    shard: int,
    sites: list[Site],
    publish: Callable[[Site], dict],
    workers: int = 1,
    max_bytes: int | None = None,
) -> tuple[dict[str, dict], dict[str, str]]:
    """Build and publish the shard's sites, largest feed first, then write its
    shard file. A site that fails keeps its previous entry and output. Returns
    each site's result and each failure's error."""
    old = read_json(store, shard_key(shard)) or {}
    results: dict[str, dict] = {}
    failures: dict[str, str] = {}
    by_size = sorted(
        sites,
        key=lambda s: -((s.catalog and s.catalog.static_bytes) or 0),
    )
    for site, result in run_all(publish, by_size, workers, max_bytes):
        if isinstance(result, BaseException):
            failures[site.slug] = str(result)
            log.warning("%s failed: %s", site.slug, failures[site.slug])
        else:
            results[site.slug] = result
    entries = {
        site.slug: results[site.slug]["entry"]
        if site.slug in results
        else old.get(site.slug)
        for site in sites
    }
    put_json(store, shard_key(shard), {k: v for k, v in entries.items() if v})
    return results, failures


def read_entries(store: Store) -> dict[str, dict]:
    """Every shard file's entries by slug."""
    entries: dict[str, dict] = {}
    for key in sorted(store.list_keys(SHARD_PREFIX)):
        entries |= read_json(store, key) or {}
    return entries


def publish_root(
    store: Store,
    entries: dict[str, dict],
    live: set[str],
    today: date,
    indexnow_key: str | None = None,
) -> list[str]:
    """Rewrite the root pages from the shard entries of the `live` sites and
    delete everything else, unless `live` shrank below PRUNE_RATIO of the
    sites listed so far. Returns the live slugs not built today."""
    listed = {slug: entry for slug, entry in entries.items() if slug in live}
    files = build_root(
        [entry["summary"] for entry in listed.values()],
        today,
        {slug: entry["pages"] for slug, entry in listed.items()},
        indexnow_key,
    )
    for path, body in files.items():
        store.put(path, body)
    if len(live) < PRUNE_RATIO * len(entries):
        log.warning(
            "only %d sites of %d listed; not deleting any", len(live), len(entries)
        )
    else:
        dropped = {
            key
            for key in store.list_keys()
            if key not in files
            and not key.startswith(STATE)
            and key.split("/", 1)[0] not in live
        }
        if dropped:
            log.info("deleting %d objects no longer built", len(dropped))
            store.delete(dropped)
    return sorted(
        slug for slug in live if entries.get(slug, {}).get("built") != today.isoformat()
    )
