"""build_site: the only entry point from a GTFS zip to a site's files."""

import io
import zipfile

from cape_flier.config import Site
from cape_flier.render import render


def build_site(zip_bytes: bytes, site: Site) -> dict[str, bytes]:
    """Map of path (relative to the site root) to file contents. No I/O."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        bad = archive.testzip()
    if bad is not None:
        raise ValueError(f"corrupt member in GTFS zip: {bad}")
    title = site.title or site.slug
    return {"index.html": render(site.style, "index.html", title=title)}
