from dataclasses import dataclass
from pathlib import Path


@dataclass
class ProcessedSegment:
    id: int

    # --- Nouveau statut après traitement ---
    status: str
    source_flow: str = "comfyui_router"

    # --- Métadonnées modifiées par ComfyUI ---
    fps: float | None = None
    resolution: str | None = None  # "1920x1080"
    nb_frames: int | None = None
    codec: str | None = None
    bitrate: int | None = None
    filesize_mb: float | None = None
    duration: float | None = None
    tags: list[str] | None = None

    # --- Enrichissements métier ---
    processed_by: str | None = None

    # --- Fichier de sortie ---
    output_path: Path | None = None
