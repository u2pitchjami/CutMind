from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from shared.executors.ffmpeg_convert import convert_safe_video_format
from shared.executors.ffprobe_utils import get_bitrate, get_codec, get_duration, get_fps, get_resolution
from shared.models.exceptions import CutMindError, ErrCode
from shared.utils.config import SAFE_FORMATS

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


# ============================================================
# 🔧 Étape 1 : Normalisation du format
# ============================================================


def normalize_format(video_path: Path) -> Path:
    """
    Si le format n'est pas supporté → convertit vers MP4.
    Lève CutMindError en cas d'échec.
    """
    ext = video_path.suffix.lower()

    if ext in SAFE_FORMATS:
        return video_path  # rien à faire

    # format non supporté → conversion
    safe_path = video_path.with_suffix(".mp4")

    try:
        convert_safe_video_format(str(video_path), str(safe_path))
    except CutMindError as err:
        # on enrichit seulement
        raise err.with_context({"step": "normalize_format"}) from err

    return safe_path


# ============================================================
# 🔧 Étape 2 : Récupération des métadonnées
# ============================================================


def get_video_metadata_all(video_path: Path) -> VideoPrepared:
    """
    Récupère TOUTES les métadonnées techniques.
    - duration
    - fps
    - resolution
    - codec
    - bitrate
    - filesize
    """
    try:
        duration = get_duration(video_path)
        fps = get_fps(video_path)
        resolution = get_resolution(video_path)
        codec = get_codec(video_path)
        bitrate = get_bitrate(video_path)
        filesize_mb = round(video_path.stat().st_size / (1024 * 1024), 2)
    except CutMindError as err:
        raise err.with_context({"step": "get_video_metadata_all"}) from err
    except Exception as exc:
        raise CutMindError(
            "Erreur inattendue lors de l'extraction des métadonnées.",
            code=ErrCode.UNEXPECTED,
            ctx={"video_path": str(video_path)},
        ) from exc

    return VideoPrepared(
        path=video_path,
        duration=duration,
        fps=fps,
        resolution=resolution,
        codec=codec,
        bitrate=bitrate,
        filesize_mb=filesize_mb,
    )


# ============================================================
# 🔧 Étape 3 : Validation métier
# ============================================================


def validate_video(prep: VideoPrepared) -> None:
    """
    Règles métier bas niveau :
    - durée > 0
    - fps cohérent
    - résolution présente
    """
    if prep.duration <= 0:
        raise CutMindError(
            "Durée vidéo invalide (<= 0).",
            code=ErrCode.FILE_ERROR,
            ctx={"video_path": str(prep.path), "duration": prep.duration},
        )

    if prep.fps <= 0:
        raise CutMindError(
            "FPS invalide (<= 0).",
            code=ErrCode.FILE_ERROR,
            ctx={"video_path": str(prep.path), "fps": prep.fps},
        )

    if not prep.resolution or "x" not in prep.resolution:
        raise CutMindError(
            "Résolution vidéo introuvable.",
            code=ErrCode.FILE_ERROR,
            ctx={"video_path": str(prep.path), "resolution": prep.resolution},
        )


# ============================================================
# 🚀 Étape 4 : Pipeline complet
# ============================================================


def prepare_video(video_path: Path) -> VideoPrepared:
    """
    Pipeline complet pour préparer une vidéo :
    1️⃣ Normalisation format
    2️⃣ Extraction métadonnées complètes
    3️⃣ Validation métier
    4️⃣ Retourne VideoPrepared
    """
    # 1. Format
    try:
        normalized_path = normalize_format(video_path)
    except CutMindError as err:
        raise err.with_context({"pipeline_step": "prepare_video"}) from err

    # 2. Metadata
    prep = get_video_metadata_all(normalized_path)

    # 3. Validation
    validate_video(prep)

    return prep
