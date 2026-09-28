import json
from datetime import date

import pytest

from cape_flier.pipeline.publish import download, publish_root, publish_site

httpx = pytest.importorskip("httpx")

TODAY = date(2026, 10, 5)


class FakeStore:
    def __init__(self, objects=None):
        self.objects = dict(objects or {})
        self.puts = []

    def list_keys(self, prefix=""):
        return {key for key in self.objects if key.startswith(prefix)}

    def get(self, key):
        return self.objects.get(key)

    def put(self, key, body):
        self.puts.append(key)
        self.objects[key] = body

    def delete(self, keys):
        for key in keys:
            self.objects.pop(key, None)


def test_publish_uploads_only_changed_and_deletes_stale():
    store = FakeStore()
    files = {"index.html": b"home", "style.css": b"css", "old/index.html": b"x"}
    assert publish_site(store, "s", files, {}, TODAY)["uploaded"] == 3
    assert store.puts == [
        "s/style.css",
        "s/index.html",
        "s/old/index.html",
        "s/manifest.json",
    ]

    store.puts.clear()
    files = {"index.html": b"new home", "style.css": b"css"}
    counts = publish_site(store, "s", files, {"url": "u"}, TODAY)
    assert counts == {"files": 2, "uploaded": 1, "deleted": 1}
    assert store.puts == ["s/index.html", "s/manifest.json"]
    assert "s/old/index.html" not in store.objects
    manifest = json.loads(store.objects["s/manifest.json"])
    assert manifest["built"] == "2026-10-05"
    assert manifest["source"] == {"url": "u"}


def test_publish_root_lists_sites_and_drops_unconfigured():
    def site(slug, built):
        summary = {"slug": slug, "title": slug.title(), "routes": 1}
        return {
            f"{slug}/site.json": json.dumps(summary).encode(),
            f"{slug}/manifest.json": json.dumps({"built": built}).encode(),
        }

    store = FakeStore(
        site("a", "2026-10-05")
        | site("b", "2026-10-04")
        | site("gone", "2026-10-05")
        | {"old-root.html": b"x"}
    )
    behind = publish_root(store, ["a", "b"], TODAY)
    assert behind == ["b"]
    assert b'href="a/"' in store.objects["index.html"]
    assert b'href="gone/"' not in store.objects["index.html"]
    assert not store.list_keys("gone/")
    assert "old-root.html" not in store.objects
    assert "a/site.json" in store.objects


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_download_records_source_headers():
    def handler(request):
        assert "if-none-match" not in request.headers
        return httpx.Response(200, content=b"zip", headers={"ETag": '"v1"'})

    body, source = download(client(handler), "https://x/g.zip", None)
    assert body == b"zip"
    assert source == {"url": "https://x/g.zip", "etag": '"v1"', "last_modified": None}


def test_download_not_modified():
    previous = {"url": "https://x/g.zip", "etag": '"v1"', "last_modified": None}

    def handler(request):
        assert request.headers["if-none-match"] == '"v1"'
        return httpx.Response(304)

    assert download(client(handler), "https://x/g.zip", previous) == (None, previous)


def test_download_ignores_previous_for_another_url():
    previous = {"url": "https://old/g.zip", "etag": '"v1"', "last_modified": None}

    def handler(request):
        assert "if-none-match" not in request.headers
        return httpx.Response(200, content=b"zip")

    body, _ = download(client(handler), "https://x/g.zip", previous)
    assert body == b"zip"
