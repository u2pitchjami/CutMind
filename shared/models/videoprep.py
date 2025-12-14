from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# ============================================================
# 📦 Modèle renvoyé après préparation vidéo
# ============================================================


@dataclass
class VideoPrepared:
    path: Path
    duration: float
    fps: float
    resolution: str
    codec: str | None
    bitrate: int | None
    filesize_mb: float

    # 🎧 Nouveaux champs audio
    has_audio: bool = False
    audio_codec: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    audio_duration: float | None = None

    # 🎞️ Pour Router
    nb_frames: int | None = None
