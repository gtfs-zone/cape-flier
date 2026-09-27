import io
import zipfile

import pytest

MINIMAL_FEED = {
    "agency.txt": "agency_id,agency_name,agency_url,agency_timezone\n"
    "a,Test Agency,https://example.org,America/New_York\n",
}


def make_zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, body in files.items():
            archive.writestr(name, body)
    return buffer.getvalue()


@pytest.fixture
def minimal_zip() -> bytes:
    return make_zip(MINIMAL_FEED)
