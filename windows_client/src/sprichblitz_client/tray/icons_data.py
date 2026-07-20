"""Eingebettete Tray-Icon-PNGs als Bytes.

Statt vorgerenderte Dateien aus ``assets/`` zu laden (was beim
PyInstaller-Build extra ``--add-data``-Hantelei bedeutet), erzeugen wir
die vier State-Icons zur Laufzeit aus reinen Solid-Color-Quadraten mit
einem winzigen Pure-Stdlib-PNG-Encoder. Das hält die Dependency-Liste
minimal (kein Pillow für die Generierung) und macht den Build
selbsterklärend.

Man kann später schönere Icons in ``assets/`` ablegen und in
``tray/icon.py`` umstellen.

Spezifikation:
- 64×64 Pixel, RGBA, 8 bit pro Channel.
- Solider Füllton mit 2 px dunklerem Rand für Sichtbarkeit auf hellen
  und dunklen Tray-Hintergründen.
"""

from __future__ import annotations

import struct
import zlib

ICON_SIZE = 64
BORDER_PX = 2

# RGBA-Tupel pro State.
COLOR_IDLE = (110, 110, 110, 255)         # neutralgrau
COLOR_RECORDING = (220, 50, 50, 255)       # kräftiges rot
COLOR_PROCESSING = (220, 180, 40, 255)     # warmes gelb
COLOR_ERROR = (140, 30, 30, 255)           # dunkelrot
COLOR_BORDER = (40, 40, 40, 255)           # dunkelgrau, einheitlich


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


def _encode_solid_png(
    fill: tuple[int, int, int, int],
    border: tuple[int, int, int, int] = COLOR_BORDER,
    size: int = ICON_SIZE,
    border_px: int = BORDER_PX,
) -> bytes:
    """Erzeugt ein solides RGBA-Quadrat mit Rand als minimales PNG."""
    rows = bytearray()
    for y in range(size):
        rows.append(0)  # PNG-Filter "None" pro Scanline.
        for x in range(size):
            on_border = (
                x < border_px
                or y < border_px
                or x >= size - border_px
                or y >= size - border_px
            )
            color = border if on_border else fill
            rows += bytes(color)

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(
        ">IIBBBBB",
        size,            # Breite
        size,            # Höhe
        8,               # Bittiefe
        6,               # Farbtyp 6 = RGBA
        0,               # Kompression
        0,               # Filter
        0,               # Interlace
    )
    idat = zlib.compress(bytes(rows), level=9)
    return (
        signature
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", idat)
        + _png_chunk(b"IEND", b"")
    )


# State-PNGs werden einmalig beim Modul-Import erzeugt – ~1 ms pro Icon,
# vernachlässigbar gegenüber dem Tk-Bootstrap.
ICON_IDLE: bytes = _encode_solid_png(COLOR_IDLE)
ICON_RECORDING: bytes = _encode_solid_png(COLOR_RECORDING)
ICON_PROCESSING: bytes = _encode_solid_png(COLOR_PROCESSING)
ICON_ERROR: bytes = _encode_solid_png(COLOR_ERROR)

ICONS: dict[str, bytes] = {
    "idle": ICON_IDLE,
    "recording": ICON_RECORDING,
    "processing": ICON_PROCESSING,
    "error": ICON_ERROR,
}
