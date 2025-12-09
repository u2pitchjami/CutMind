# cutmind/models/db_models.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
import uuid


# -------------------------------------------------------------
# 🧩 SEGMENT : version unique (DB + logique)
# -------------------------------------------------------------
@dataclass
class Segment:
    id: int | None = None
    uid: str = field(default_factory=lambda: str(uuid.uuid4()))
    video_id: int = 0
    start: float = 0.0
    end: float = 0.0
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
    nb_frames: int | None = None
    codec: str | None = None
    bitrate: int | None = None
    has_audio: bool | None = None
    audio_codec: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    audio_duration: float | None = None
    filesize_mb: float | None = None
    filename_predicted: str | None = None
    output_path: str | None = None
    enhanced_path: str | None = None
    merged_from: list[str] = field(default_factory=list)
    merge_count: int = 0
    tags: list[str] = field(default_factory=list)
    error: str | None = None
    created_at: datetime | None = None
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())
    keywords: list[str] = field(default_factory=list)

    # --- Factory : construit à partir d’une ligne SQL
    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Segment:
        allowed = cls.__annotations__.keys()
        data = {k: row[k] for k in row if k in allowed}

        # Sécurise les listes pour éviter les None
        data["tags"] = data.get("tags") or []
        data["keywords"] = data.get("keywords") or []
        data["merged_from"] = data.get("merged_from") or []
        if "sample_rate" in data and data["sample_rate"] is not None:
            data["sample_rate"] = int(data["sample_rate"])

        if "channels" in data and data["channels"] is not None:
            data["channels"] = int(data["channels"])

        if "audio_duration" in data and data["audio_duration"] is not None:
            data["audio_duration"] = float(data["audio_duration"])

        if "nb_frames" in data and data["nb_frames"] is not None:
            data["nb_frames"] = int(data["nb_frames"])
        return cls(**data)

    # --- Prépare les valeurs pour un INSERT/UPDATE
    def to_db_dict(self) -> dict[str, Any]:
        data = self.__dict__.copy()
        data.pop("keywords", None)
        return data

    def add_tag(self, tag: str) -> None:
        """Ajoute un tag sans doublon."""
        if tag not in self.tags:
            self.tags.append(tag)

    def has_tag(self, tag: str) -> bool:
        return tag in self.tags

    def compute_duration(self) -> None:
        """Calcule et met à jour la durée du segment."""
        self.duration = round(self.end - self.start, 3)
        self.last_updated = datetime.now().isoformat()

    def predict_filename(self, base_dir: str | Path = "./outputs", folder_name: str = "folder") -> None:
        """
        Génère un nom de fichier prédictif stable et unique.
        Exemple : seg_0001_a1b2c3d4.mp4
        """
        base = Path(base_dir) / folder_name
        base.mkdir(parents=True, exist_ok=True)
        name = f"seg_{self.id:04d}_{self.uid}.mp4"
        self.filename_predicted = name
        self.output_path = str(base / name)
        self.last_updated = datetime.now().isoformat()


# -------------------------------------------------------------
# 🎬 VIDEO : version unique (DB + logique)
# -------------------------------------------------------------
@dataclass
class Video:
    id: int | None = None
    uid: str = ""
    name: str = ""
    video_path: str | None = None
    duration: float | None = None
    fps: float | None = None
    resolution: str | None = None
    codec: str | None = None
    bitrate: int | None = None
    filesize_mb: float | None = None
    status: str = "init"
    origin: str | None = "smartcut"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())
    segments: list[Segment] = field(default_factory=list)

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Video:
        allowed = cls.__annotations__.keys()
        data = {k: row[k] for k in row if k in allowed}
        return cls(**data)

    def finalize_segments(self, output_dir: str | Path = "./outputs") -> None:
        """
        Calcule la durée et le nom de fichier de sortie pour chaque segment.
        """
        folder_name = self.name if self.name else f"video_{self.id or 0}"
        for seg in self.segments:
            seg.compute_duration()
            seg.predict_filename(output_dir, folder_name)
            seg.video_id = self.id or 0
            seg.fps = self.fps
            seg.resolution = self.resolution
            seg.codec = self.codec
            seg.bitrate = self.bitrate
        self.last_updated = datetime.now().isoformat()

    def get_pending_segments(self) -> list[Segment]:
        """Retourne les segments non traités par l'IA."""
        return [s for s in self.segments if s.status != "ai_done"]


# -------------------------------------------------------------
# 🏷️ KEYWORD : table simple
# -------------------------------------------------------------
@dataclass
class Keyword:
    id: int | None = None
    keyword: str = ""
