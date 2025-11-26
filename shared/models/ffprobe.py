from __future__ import annotations

from typing import TypedDict

# ============================================================
# 🧩 TypedDict : structure FFprobe JSON
# ============================================================


class FFprobeFormat(TypedDict, total=False):
    duration: str
    bit_rate: str


class FFprobeStream(TypedDict, total=False):
    codec_type: str
    codec_name: str
    width: int
    height: int
    avg_frame_rate: str


class FFprobeData(TypedDict):
    streams: list[FFprobeStream]
    format: FFprobeFormat
