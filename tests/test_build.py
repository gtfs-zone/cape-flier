import pytest

from cape_flier.build import build_site
from cape_flier.config import Site


def test_empty_build(minimal_zip):
    site = Site(slug="test", url="https://example.org/g.zip", title="Test & Co")
    files = build_site(minimal_zip, site)
    assert set(files) == {"index.html"}
    assert b"<h1>Test &amp; Co</h1>" in files["index.html"]


def test_rail_style_falls_back_to_classic_templates(minimal_zip):
    site = Site(slug="rail", url="https://example.org/g.zip", style="rail")
    assert b"<h1>rail</h1>" in build_site(minimal_zip, site)["index.html"]


def test_not_a_zip():
    site = Site(slug="test", url="https://example.org/g.zip")
    with pytest.raises(Exception, match="zip"):
        build_site(b"not a zip", site)
