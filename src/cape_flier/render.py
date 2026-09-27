"""Jinja environment over styles/, rendering pages to bytes."""

from functools import cache

from jinja2 import Environment, PackageLoader, StrictUndefined

from cape_flier.config import Style

BASE_STYLE: Style = "classic"


@cache
def environment() -> Environment:
    return Environment(
        loader=PackageLoader("cape_flier", "styles"),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def render(style: Style, template: str, **context: object) -> bytes:
    """Render styles/<style>/<template>, falling back to the classic style."""
    page = environment().select_template(
        [f"{style}/{template}", f"{BASE_STYLE}/{template}"]
    )
    return page.render(**context).encode()
