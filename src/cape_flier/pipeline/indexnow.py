"""Tell IndexNow search engines (Bing, Yandex, Seznam, ...) which pages changed."""

import logging

import httpx

from cape_flier.build import BASE_URL

log = logging.getLogger(__name__)

ENDPOINT = "https://api.indexnow.org/indexnow"
# IndexNow keys are public: the bucket root serves it as <key>.txt.
KEY = "23c63a4f9e2ddd584a4e284b82473960"


def ping(http: httpx.Client, urls: list[str]) -> None:
    """Submit `urls`; failures are logged, never raised."""
    if not urls:
        return
    body = {
        "host": BASE_URL.removeprefix("https://"),
        "key": KEY,
        "keyLocation": f"{BASE_URL}/{KEY}.txt",
        "urlList": urls,
    }
    try:
        response = http.post(ENDPOINT, json=body)
    except httpx.HTTPError:
        log.warning("IndexNow request failed", exc_info=True)
        return
    if response.status_code in (200, 202):
        log.info("IndexNow accepted %d urls", len(urls))
    else:
        log.warning("IndexNow returned %d: %s", response.status_code, response.text)
