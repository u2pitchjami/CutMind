# cutmind/models/db_models.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# -------------------------------------------------------------
# 🧩 SEGMENT : version unique (DB + logique)
# -------------------------------------------------------------
@dataclass
class Segment:
    id: int | None = None
    uid: str = ""
    video_id: int = 0
    start: float | None = None
    end: float | None = None
    duration: float | None = None
    status: str = "raw"
    confidence: float | None = None
    description: str | None = None
    rating: int | None = None
    quality_score: float | None = None
    category: str | None = None
    ai_model: str | None = None
    processed_by: str | None = None
    source_flow: str | None = None
    resolution: str | None = None
    fps: float | None = None
    codec: str | None = None
    bitrate: int | None = None
    filesize_mb: float | None = None
    filename_predicted: str | None = None
    output_path: str | None = None
    enhanced_path: str | None = None
    merged_from: list[str] = field(default_factory=list)
    merge_count: int = 0
    tags: list[str] = field(default_factory=list)
    error: str | None = None
    created_at: datetime | None = None
    last_updated: datetime | None = None
    keywords: list[str] = field(default_factory=list)

    # --- Factory : construit à partir d’une ligne SQL
    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Segment:
        allowed = cls.__annotations__.keys()
        data = {k: row[k] for k in row if k in allowed}
        return cls(**data)

    # --- Prépare les valeurs pour un INSERT/UPDATE
    def to_db_dict(self) -> dict[str, Any]:
        data = self.__dict__.copy()
        data.pop("keywords", None)
        return data


# -------------------------------------------------------------
# 🎬 VIDEO : version unique (DB + logique)
# -------------------------------------------------------------
@dataclass
class Video:
    id: int | None = None
    uid: str = ""
    name: str = ""
    duration: float | None = None
    fps: float | None = None
    resolution: str | None = None
    codec: str | None = None
    bitrate: int | None = None
    filesize_mb: float | None = None
    status: str = "init"
    origin: str | None = "smartcut"
    created_at: datetime | None = None
    last_updated: datetime | None = None
    segments: list[Segment] = field(default_factory=list)

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Video:
        allowed = cls.__annotations__.keys()
        data = {k: row[k] for k in row if k in allowed}
        return cls(**data)


# -------------------------------------------------------------
# 🏷️ KEYWORD : table simple
# -------------------------------------------------------------
@dataclass
class Keyword:
    id: int | None = None
    keyword: str = ""
