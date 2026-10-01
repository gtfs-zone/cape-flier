"""Hashed route colors, a port of gtfs-zone-web-common's `gtfs/route-colors.ts`.

A route without a `route_color` gets a hue hashed from its `route_id`, spread
by the golden angle and rendered through OKLCH at a fixed lightness and chroma,
so every hashed route has the same apparent weight. Output matches gtfs-zone-web-common
hex for hex.
"""

import math

HASH_LIGHTNESS = 0.62
HASH_CHROMA = 0.11
# Golden angle, so sequential ids land far apart in hue.
HUE_STEP = 137.508


def int32(value: int) -> int:
    """Wrap to a signed 32-bit integer, as JS bitwise operators do."""
    value &= 0xFFFFFFFF
    return value - 0x100000000 if value & 0x80000000 else value


def hash_string(value: str) -> int:
    """djb2-style hash over UTF-16 code units, matching the JS `hashString`."""
    data = value.encode("utf-16-le")
    h = 0
    for i in range(0, len(data), 2):
        code = data[i] | data[i + 1] << 8
        h = int32((h << 5) - h + code)
    return abs(h)


def channel_to_hex(value: float) -> str:
    """Linear-light channel to two hex digits, gamma-encoded and clamped."""
    if value <= 0.0031308:
        gamma = 12.92 * value
    else:
        gamma = 1.055 * max(value, 0) ** (1 / 2.4) - 0.055
    # JS Math.round, not Python's round-half-to-even.
    byte = math.floor(min(1.0, max(0.0, gamma)) * 255 + 0.5)
    return f"{byte:02X}"


def oklch_to_hex(lightness: float, chroma: float, hue: float) -> str:
    """OKLCH to RRGGBB via OKLab and linear sRGB, clamped per channel."""
    radians = hue * math.pi / 180
    a = chroma * math.cos(radians)
    b = chroma * math.sin(radians)

    l_ = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (lightness - 0.0894841775 * a - 1.291485548 * b) ** 3

    red = 4.0767416621 * l_ - 3.3077115913 * m + 0.2309699292 * s
    green = -1.2684380046 * l_ + 2.6097574011 * m - 0.3413193965 * s
    blue = -0.0041960863 * l_ - 0.7034186147 * m + 1.707614701 * s
    return channel_to_hex(red) + channel_to_hex(green) + channel_to_hex(blue)


def route_color(route_id: str, color: str | None) -> str:
    """The feed's color when it has one, else a hue hashed from `route_id`."""
    if color is not None:
        return color
    hue = (hash_string(route_id) * HUE_STEP) % 360
    return oklch_to_hex(HASH_LIGHTNESS, HASH_CHROMA, hue)
