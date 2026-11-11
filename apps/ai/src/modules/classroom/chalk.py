"""Original chalk pictures and a stroke alphabet.

These PNGs are drawn in this file. They are not copied from a font or a
photo. The website stamps the chalk dab along each stroke and moves the
chalk cursor with the voice. It must not typeset the words in a font.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "assets"

NAMES = {
    "blackboard": "blackboard.png",
    "chalk_white": "chalk-white.png",
    "chalk_yellow": "chalk-yellow.png",
    "cursor": "cursor-chalk.png",
    "part_sun": "part-sun.png",
    "part_leaf": "part-leaf.png",
    "part_arrow": "part-arrow.png",
    "part_drop": "part-drop.png",
}

# Each letter is a few uneven strokes in a 0..1 box, so the line looks written, not typed.
_GLYPHS: dict[str, list[list[tuple[float, float]]]] = {
    "a": [[(0.15, 0.62), (0.5, 0.38), (0.82, 0.7)], [(0.5, 0.55), (0.84, 0.95)]],
    "b": [[(0.22, 0.08), (0.2, 0.95)], [(0.2, 0.5), (0.72, 0.48), (0.7, 0.92), (0.22, 0.9)]],
    "c": [[(0.78, 0.42), (0.4, 0.36), (0.18, 0.68), (0.48, 0.96), (0.8, 0.82)]],
    "d": [[(0.74, 0.08), (0.76, 0.95)], [(0.74, 0.48), (0.28, 0.5), (0.22, 0.9), (0.72, 0.92)]],
    "e": [[(0.8, 0.58), (0.22, 0.55)], [(0.22, 0.55), (0.3, 0.36), (0.72, 0.4)], [(0.22, 0.55), (0.28, 0.94), (0.74, 0.88)]],
    "f": [[(0.72, 0.22), (0.4, 0.08), (0.32, 0.95)], [(0.18, 0.48), (0.68, 0.46)]],
    "g": [[(0.78, 0.4), (0.3, 0.42), (0.24, 0.9), (0.7, 0.88), (0.74, 1.15)]],
    "h": [[(0.22, 0.08), (0.24, 0.95)], [(0.24, 0.52), (0.7, 0.48), (0.78, 0.95)]],
    "i": [[(0.48, 0.28), (0.46, 0.34)], [(0.42, 0.48), (0.5, 0.95)]],
    "j": [[(0.55, 0.28), (0.53, 0.34)], [(0.58, 0.48), (0.6, 0.95), (0.3, 1.12)]],
    "k": [[(0.24, 0.08), (0.26, 0.95)], [(0.74, 0.42), (0.32, 0.68), (0.78, 0.96)]],
    "l": [[(0.4, 0.08), (0.36, 0.78), (0.62, 0.95)]],
    "m": [[(0.12, 0.95), (0.16, 0.48), (0.42, 0.72), (0.58, 0.46), (0.86, 0.95)]],
    "n": [[(0.18, 0.95), (0.2, 0.48), (0.78, 0.95)]],
    "o": [[(0.5, 0.38), (0.18, 0.66), (0.48, 0.96), (0.82, 0.64), (0.5, 0.38)]],
    "p": [[(0.24, 0.4), (0.22, 1.16)], [(0.24, 0.42), (0.74, 0.46), (0.7, 0.86), (0.24, 0.88)]],
    "q": [[(0.72, 0.4), (0.74, 1.16)], [(0.72, 0.42), (0.26, 0.48), (0.24, 0.88), (0.7, 0.9)]],
    "r": [[(0.28, 0.95), (0.3, 0.46)], [(0.3, 0.55), (0.55, 0.4), (0.82, 0.5)]],
    "s": [[(0.74, 0.42), (0.36, 0.36), (0.28, 0.58), (0.7, 0.7), (0.62, 0.96), (0.22, 0.9)]],
    "t": [[(0.46, 0.22), (0.4, 0.95)], [(0.22, 0.4), (0.74, 0.36)]],
    "u": [[(0.2, 0.42), (0.24, 0.82), (0.72, 0.78), (0.76, 0.42)]],
    "v": [[(0.16, 0.4), (0.48, 0.96), (0.84, 0.38)]],
    "w": [[(0.1, 0.4), (0.28, 0.96), (0.5, 0.58), (0.72, 0.96), (0.9, 0.4)]],
    "x": [[(0.2, 0.4), (0.8, 0.96)], [(0.78, 0.4), (0.18, 0.96)]],
    "y": [[(0.18, 0.4), (0.48, 0.78), (0.82, 0.38)], [(0.48, 0.78), (0.4, 1.14)]],
    "z": [[(0.2, 0.42), (0.8, 0.4)], [(0.8, 0.4), (0.18, 0.94)], [(0.18, 0.94), (0.82, 0.96)]],
    "0": [[(0.5, 0.36), (0.2, 0.66), (0.5, 0.96), (0.8, 0.66), (0.5, 0.36)]],
    "1": [[(0.32, 0.48), (0.52, 0.36), (0.48, 0.96)]],
    "2": [[(0.22, 0.48), (0.5, 0.34), (0.78, 0.5), (0.22, 0.96), (0.8, 0.94)]],
    "3": [[(0.24, 0.42), (0.7, 0.38), (0.4, 0.64), (0.74, 0.78), (0.28, 0.96)]],
    "4": [[(0.68, 0.96), (0.64, 0.36)], [(0.64, 0.36), (0.2, 0.72), (0.78, 0.7)]],
    "5": [[(0.74, 0.4), (0.28, 0.38)], [(0.28, 0.38), (0.26, 0.62), (0.7, 0.6), (0.72, 0.9), (0.24, 0.96)]],
    "6": [[(0.72, 0.42), (0.36, 0.38), (0.22, 0.7), (0.5, 0.96), (0.76, 0.72), (0.28, 0.66)]],
    "7": [[(0.2, 0.4), (0.8, 0.38), (0.4, 0.96)]],
    "8": [[(0.5, 0.36), (0.22, 0.52), (0.5, 0.66), (0.78, 0.52), (0.5, 0.36)], [(0.5, 0.66), (0.24, 0.84), (0.5, 0.98), (0.76, 0.84), (0.5, 0.66)]],
    "9": [[(0.28, 0.92), (0.64, 0.96), (0.78, 0.62), (0.5, 0.38), (0.24, 0.58), (0.7, 0.66)]],
    ".": [[(0.46, 0.9), (0.54, 0.96)]],
    "?": [[(0.24, 0.4), (0.55, 0.3), (0.7, 0.5), (0.48, 0.7)], [(0.46, 0.9), (0.52, 0.96)]],
    "+": [[(0.2, 0.66), (0.8, 0.66)], [(0.5, 0.4), (0.5, 0.92)]],
}


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def write_png(path: Path, width: int, height: int, pixels: bytes) -> None:
    raw = b"".join(b"\x00" + pixels[y * width * 4 : (y + 1) * width * 4] for y in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b"")
    )


def _blank(width: int, height: int, colour: tuple[int, int, int, int]) -> bytearray:
    return bytearray(colour * (width * height))


def _dot(pixels: bytearray, width: int, height: int, x: int, y: int, colour: tuple[int, int, int, int]) -> None:
    if 0 <= x < width and 0 <= y < height:
        i = (y * width + x) * 4
        pixels[i : i + 4] = bytes(colour)


def _disc(pixels: bytearray, width: int, height: int, cx: float, cy: float, radius: float, colour) -> None:
    r = int(radius) + 1
    for y in range(int(cy) - r, int(cy) + r + 1):
        for x in range(int(cx) - r, int(cx) + r + 1):
            if (x - cx) ** 2 + (y - cy) ** 2 <= radius * radius:
                _dot(pixels, width, height, x, y, colour)


def ensure_assets() -> dict[str, str]:
    """Write the chalk PNGs if they are missing, then return their file names."""
    ASSETS.mkdir(parents=True, exist_ok=True)
    _board()
    _dab("chalk-white.png", (236, 232, 214, 230))
    _dab("chalk-yellow.png", (244, 214, 102, 230))
    _cursor()
    _sun()
    _leaf()
    _arrow()
    _drop()
    (ASSETS / "LICENSE.txt").write_text(
        "Original drawings made for the Sybeez AI teacher.\n"
        "No third-party font, photo, or clipart is included.\n"
        "The school website may use these PNGs to draw the chalkboard.\n",
        encoding="utf-8",
    )
    return dict(NAMES)


def _board() -> None:
    width = height = 48
    pixels = _blank(width, height, (28, 64, 42, 255))
    for y in range(height):
        for x in range(width):
            noise = ((x * 17 + y * 31) % 11) - 5
            _dot(pixels, width, height, x, y, (28 + noise, 64 + noise, 42, 255))
    write_png(ASSETS / "blackboard.png", width, height, bytes(pixels))


def _dab(name: str, colour: tuple[int, int, int, int]) -> None:
    size = 16
    pixels = _blank(size, size, (0, 0, 0, 0))
    _disc(pixels, size, size, 8, 8, 5.5, colour)
    _disc(pixels, size, size, 6, 6, 2, (255, 255, 255, 90))
    write_png(ASSETS / name, size, size, bytes(pixels))


def _cursor() -> None:
    size = 32
    pixels = _blank(size, size, (0, 0, 0, 0))
    for t in range(18):
        _disc(pixels, size, size, 6 + t * 0.9, 26 - t * 1.1, 2.2, (232, 228, 210, 255))
    _disc(pixels, size, size, 22, 6, 3.2, (80, 80, 80, 255))
    write_png(ASSETS / "cursor-chalk.png", size, size, bytes(pixels))


def _sun() -> None:
    size = 48
    pixels = _blank(size, size, (0, 0, 0, 0))
    _disc(pixels, size, size, 24, 24, 8, (244, 214, 102, 255))
    for angle in range(8):
        dx = (angle % 4) - 1.5
        dy = (angle // 4) - 0.5
        for step in range(6, 14):
            _dot(pixels, size, size, int(24 + dx * step), int(24 + dy * step), (244, 214, 102, 255))
    write_png(ASSETS / "part-sun.png", size, size, bytes(pixels))


def _leaf() -> None:
    size = 48
    pixels = _blank(size, size, (0, 0, 0, 0))
    for y in range(14, 36):
        half = int(8 - abs(y - 24) * 0.5)
        for x in range(16 - half, 34 + half):
            _dot(pixels, size, size, x, y, (186, 214, 140, 255))
    for y in range(16, 34):
        _dot(pixels, size, size, 24, y, (80, 110, 60, 255))
    write_png(ASSETS / "part-leaf.png", size, size, bytes(pixels))


def _arrow() -> None:
    size = 48
    pixels = _blank(size, size, (0, 0, 0, 0))
    colour = (236, 232, 214, 255)
    for x in range(8, 36):
        _dot(pixels, size, size, x, 24, colour)
        _dot(pixels, size, size, x, 25, colour)
    for step in range(8):
        _dot(pixels, size, size, 30 + step, 24 - step, colour)
        _dot(pixels, size, size, 30 + step, 24 + step, colour)
    write_png(ASSETS / "part-arrow.png", size, size, bytes(pixels))


def _drop() -> None:
    size = 48
    pixels = _blank(size, size, (0, 0, 0, 0))
    _disc(pixels, size, size, 24, 28, 8, (170, 210, 230, 255))
    for y in range(10, 24):
        half = max(1, (y - 8) // 3)
        for x in range(24 - half, 24 + half):
            _dot(pixels, size, size, x, y, (170, 210, 230, 255))
    write_png(ASSETS / "part-drop.png", size, size, bytes(pixels))


def asset_urls() -> dict[str, str]:
    ensure_assets()
    return {key: f"/api/v1/ai/classroom/chalk/{filename}" for key, filename in NAMES.items()}


def handwriting(text: str, *, x: float, y: float, chalk: str = "white", width: float = 0.045) -> list[dict]:
    """Turn words into chalk strokes. The website draws these. It does not print the string."""
    events = []
    cursor_x = x
    cursor_y = y
    for char in (text or "").lower():
        if char == " ":
            cursor_x += width * 0.7
            continue
        if cursor_x > 0.88:
            cursor_x = x
            cursor_y += 0.11
        glyph = _GLYPHS.get(char)
        if glyph is None:
            continue
        for stroke in glyph:
            points = [{"x": round(cursor_x + px * width, 4), "y": round(cursor_y + py * 0.09, 4)} for px, py in stroke]
            events.append({"type": "chalk_stroke", "chalk": chalk, "stamp": "chalk-white" if chalk == "white" else "chalk-yellow", "points": points})
            end = points[-1]
            events.append({"type": "hand", "asset": "cursor-chalk", "x": end["x"], "y": end["y"]})
        cursor_x += width * 1.15
    return events


def time_events(events: list[dict], duration_ms: int) -> list[dict]:
    if not events:
        return []
    step = max(duration_ms, 1) / len(events)
    timed = []
    for index, event in enumerate(events):
        timed.append({"at_ms": int(index * step), **event})
    return timed
