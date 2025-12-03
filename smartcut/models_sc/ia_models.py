from __future__ import annotations

from dataclasses import dataclass


@dataclass
class IASegmentInput:
    """
    Ce que le pipeline IA reçoit pour chaque segment à analyser.
    - mode complet : source_path = vidéo originale, start/end = timing du segment
    - mode lite    : source_path = fichier du segment découpé, start/end = timing relatif à ce fichier
    """

    segment_id: int
    start: float
    end: float
    source_path: str  # vidéo originale OU vidéo du segment (lite)


@dataclass
class IASegmentResult:
    """
    Résultat IA pour un segment.
    """

    segment_id: int
    description: str
    keywords: list[str]
    model_name: str | None = None
    error: str | None = None
