"""Jinja environment over templates/, rendering pages to bytes."""

from functools import cache

from jinja2 import Environment, PackageLoader, StrictUndefined

from gtfs_zone_timetable_sites.pages import long_date


@cache
def environment() -> Environment:
    env = Environment(
        loader=PackageLoader("gtfs_zone_timetable_sites", "templates"),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["long_date"] = long_date
    return env


def asset(name: str) -> bytes:
    """A static file from templates/."""
    env = environment()
    return env.loader.get_source(env, name)[0].encode()


def render(template: str, **context: object) -> bytes:
    """Render templates/<template>."""
    return environment().get_template(template).render(**context).encode()
