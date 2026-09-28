from conftest import fixture_zip

from cape_flier.cli import main


def test_build_from_local_zip(tmp_path):
    config = tmp_path / "sites.yaml"
    config.write_text("sites: [{slug: local, url: 'https://example.org/g.zip'}]")
    feed = tmp_path / "feed.zip"
    feed.write_bytes(fixture_zip("overnight"))
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


def test_dump_prints_timetables(tmp_path, capsys):
    config = tmp_path / "sites.yaml"
    config.write_text("sites: [{slug: local, url: 'https://example.org/g.zip'}]")
    feed = tmp_path / "feed.zip"
    feed.write_bytes(fixture_zip("overnight"))
    main(
        [
            "dump",
            "--site",
            "local",
            "--zip",
            str(feed),
            "--config",
            str(config),
            "--date",
            "2026-10-05",
        ]
    )
    out = capsys.readouterr().out
    assert "# 1" in out
    assert "11:40p" in out and "12:10a+1" not in out
