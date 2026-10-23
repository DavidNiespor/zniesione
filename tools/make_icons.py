"""Ikony aplikacji (PWA): żółte jajo na ciemnozielonym tle w kolorach portalu. Czysty Python, bez bibliotek.
Uruchom: python tools/make_icons.py  (zapisuje zniesione/static/icons/*.png)"""
import os
import struct
import zlib

BG, EGG, SHINE = (0x1E, 0x3A, 0x2F), (0xF0, 0xB4, 0x00), (0xFF, 0xE0, 0x7A)
OUT = os.path.join(os.path.dirname(__file__), "..", "zniesione", "static", "icons")


def png(path, w, h, rows):
    raw = b"".join(b"\x00" + bytes(r) for r in rows)
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def inside_egg(x, y, cx, cy, rx, ry):
    """Jajo: elipsa węższa u góry."""
    t = (y - cy) / ry
    k = rx * (1 + 0.2 * t) if t < 0 else rx
    return ((x - cx) / k) ** 2 + t * t <= 1


def icon(size, scale, path, ss=3):
    cx, cy, rx, ry = size / 2, size * 0.53, size * 0.30 * scale, size * 0.38 * scale
    rows = []
    for py in range(size):
        row = []
        for px in range(size):
            acc = [0, 0, 0]
            for sy in range(ss):
                for sx in range(ss):
                    x, y = px + (sx + .5) / ss, py + (sy + .5) / ss
                    if inside_egg(x, y, cx, cy, rx, ry):
                        c = SHINE if inside_egg(x, y, cx - rx * .32, cy - ry * .38, rx * .22, ry * .16) else EGG
                    else:
                        c = BG
                    for i in range(3):
                        acc[i] += c[i]
            row += [round(a / ss / ss) for a in acc]
        rows.append(row)
    png(path, size, size, rows)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for name, size, scale in (("icon-192.png", 192, 1), ("icon-512.png", 512, 1), ("maskable-512.png", 512, .78),
                              ("apple-touch-icon.png", 180, .9), ("favicon-32.png", 32, 1.1)):
        icon(size, scale, os.path.join(OUT, name), 2 if size >= 512 else 3)
        print("zapisano", name)
