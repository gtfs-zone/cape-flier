"""Dagster entrypoint: one partition per site in sites.yaml, rebuilt daily.

Each run builds one site and then rewrites the bucket root, so the root index
is current after every run. The Gatus heartbeat is pushed only once every
configured site has been built today.
"""

import os
from datetime import date
from pathlib import Path

import httpx
from dagster import (
    AssetExecutionContext,
    DefaultScheduleStatus,
    Definitions,
    MaterializeResult,
    MetadataValue,
    RunRequest,
    ScheduleEvaluationContext,
    StaticPartitionsDefinition,
    asset,
    define_asset_job,
    schedule,
)

from cape_flier.build import BASE_URL, build_site
from cape_flier.config import FEEDS_URL, USER_AGENT, load_config
from cape_flier.pipeline.bucket import Bucket, BucketSettings
from cape_flier.pipeline.heartbeat import push_heartbeat
from cape_flier.pipeline.publish import (
    download,
    publish_root,
    publish_site,
    read_manifest,
)

CONFIG = load_config(
    Path(os.environ.get("CAPE_FLIER_CONFIG", "sites.yaml")).read_text()
)
SLUGS = [site.slug for site in CONFIG.sites]

site_partitions = StaticPartitionsDefinition(SLUGS)


@asset(partitions_def=site_partitions)
def site_pages(context: AssetExecutionContext) -> MaterializeResult:
    """Download the site's feed, build it and publish the changed files."""
    site = CONFIG.site(context.partition_key)
    today = date.today()
    bucket = Bucket(BucketSettings.from_env())
    previous = read_manifest(bucket, site.slug)
    # Builds depend on the date, so only a second run on the same day may skip.
    same_day = previous and previous.get("built") == today.isoformat()
    with httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=120.0, follow_redirects=True
    ) as http:
        feeds_doc = http.get(FEEDS_URL).raise_for_status().json() if site.feed else {}
        url = site.download_url(feeds_doc)
        body, source = download(http, url, previous["source"] if same_day else None)

    if body is None:
        context.log.info("feed unchanged since today's build, not rebuilding")
        counts = {"files": len(previous["files"]), "uploaded": 0, "deleted": 0}
    else:
        files = build_site(body, site, today)
        counts = publish_site(bucket, site.slug, files, source, today)
    context.log.info("%s: %s", site.slug, counts)

    behind = publish_root(bucket, SLUGS, today)
    if behind:
        context.log.info("not built today yet: %s", ", ".join(behind))
    else:
        push_heartbeat()

    return MaterializeResult(
        metadata={
            **counts,
            "feed_url": MetadataValue.url(url),
            "site": MetadataValue.url(f"{BASE_URL}/{site.slug}/"),
        }
    )


sites_job = define_asset_job(
    "sites", selection=[site_pages], partitions_def=site_partitions
)


# Two hours after geometry-car's 09:00 UTC catalog run, which shares the run
# queue and publishes the feeds.json this resolves feed ids from.
@schedule(
    job=sites_job,
    cron_schedule="0 11 * * *",
    execution_timezone="UTC",
    default_status=DefaultScheduleStatus.RUNNING,
)
def daily_sites(context: ScheduleEvaluationContext) -> list[RunRequest]:
    day = context.scheduled_execution_time.date().isoformat()
    return [RunRequest(run_key=f"{slug}-{day}", partition_key=slug) for slug in SLUGS]


defs = Definitions(assets=[site_pages], jobs=[sites_job], schedules=[daily_sites])
