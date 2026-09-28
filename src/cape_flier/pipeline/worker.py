"""One site's download, build and publish, run in a worker process with its
own bucket and HTTP clients from the environment."""

from datetime import date

import httpx

from cape_flier.config import USER_AGENT, Site
from cape_flier.pipeline.bucket import Bucket, BucketSettings
from cape_flier.pipeline.publish import build_and_publish


def publish_one(site: Site, today: date, version: str) -> dict:
    bucket = Bucket(BucketSettings.from_env())
    with httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=120.0, follow_redirects=True
    ) as http:
        return build_and_publish(bucket, http, site, today, version)
