from __future__ import annotations

from pathlib import Path

from shared.executors.ffmpeg_convert import convert_safe_video_format
from shared.executors.ffprobe_utils import (
    get_metadata_all,
)
from shared.models.exceptions import CutMindError, ErrCode
from shared.models.videoprep import VideoPrepared
from shared.utils.config import SAFE_FORMATS

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
# 🔧 Étape 3 : Validation métier
# ============================================================


def validate_video(prep: VideoPrepared) -> None:
    """
    Règles métier bas niveau :
    - durée > 0
    - fps cohérent
    - résolution présente
    """

    # Support dict (TypedDict)
    if isinstance(prep, dict):
        duration = prep.get("duration", 0)
        fps = prep.get("fps", 0)
        resolution = prep.get("resolution", "")
    else:
        duration = prep.duration
        fps = prep.fps
        resolution = prep.resolution

    if duration <= 0:
        raise CutMindError(
            "Durée vidéo invalide (<= 0).",
            code=ErrCode.FILE_ERROR,
            ctx={"duration": duration},
        )

    if fps <= 0:
        raise CutMindError(
            "FPS invalide (<= 0).",
            code=ErrCode.FILE_ERROR,
            ctx={"fps": fps},
        )

    if not resolution or "x" not in resolution:
        raise CutMindError(
            "Résolution vidéo introuvable.",
            code=ErrCode.FILE_ERROR,
            ctx={"resolution": resolution},
        )


# ============================================================
# 🚀 Étape 4 : Pipeline complet
# ============================================================


def prepare_video(video_path: Path) -> VideoPrepared:
    """
    Pipeline complet en version optimisée :
    - 1 seul ffprobe
    - validation basée sur VideoMetadata
    - retour d’un dict directement
    """
    try:
        normalized_path = normalize_format(video_path)
    except CutMindError as err:
        raise err.with_context({"pipeline_step": "prepare_video"}) from err

    # 1 seul ffprobe
    try:
        meta = get_metadata_all(normalized_path)
    except CutMindError as err:
        raise err.with_context({"pipeline_step": "metadata_extraction"}) from err

    # validation (dict-compatible)
    validate_video(meta)

    return meta
