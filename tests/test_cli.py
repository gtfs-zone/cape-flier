from cape_flier.cli import main


def test_build_from_local_zip(tmp_path, minimal_zip):
    config = tmp_path / "sites.yaml"
    config.write_text("sites: [{slug: local, url: 'https://example.org/g.zip'}]")
    feed = tmp_path / "feed.zip"
    feed.write_bytes(minimal_zip)
    out = tmp_path / "dist"
    main(
        [
            "build",
            "--site",
            "local",
            "--zip",
            str(feed),
            "--out",
            str(out),
            "--config",
            str(config),
        ]
    )
    assert (out / "local" / "index.html").read_bytes().startswith(b"<!doctype html>")
