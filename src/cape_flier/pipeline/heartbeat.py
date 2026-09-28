"""Push a success result to a Gatus external endpoint."""

import logging
import os

import httpx

log = logging.getLogger(__name__)

ENDPOINT_KEY = "data_sites-publish"


def push_heartbeat() -> bool:
    """POST success to Gatus. Returns whether it was accepted; never raises."""
    base = os.environ.get("GATUS_URL", "")
    if not base:
        log.info("GATUS_URL unset; not pushing a heartbeat")
        return False
    url = f"{base.rstrip('/')}/api/v1/endpoints/{ENDPOINT_KEY}/external"
    token = os.environ.get("GATUS_TOKEN", "")
    try:
        response = httpx.post(
            url,
            params={"success": "true"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("gatus heartbeat push failed: %s", exc)
        return False
    return True
