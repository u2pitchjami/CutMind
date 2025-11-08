"""
Validation et parsing des JSON Smartcut
=======================================

- Détecte automatiquement le type : standard ou lite
- Validation stricte avec Pydantic
- Tolère les champs null (None)
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field, ValidationError

from cutmind.models.db_models import Segment, Video
from shared.utils.logger import get_logger

logger = get_logger(__name__)


# ------------------------------------------------------------
# 🧩 SEGMENT
# ------------------------------------------------------------
class SmartcutSegment(BaseModel):
    uid: str
    start: float
    end: float
    duration: float
    description: str | None = None
    source_flow: Literal["auto_validation", "manual_review"] | None = None
    keywords: list[str] = Field(default_factory=list)
    status: str | None = None
    confidence: float | None = None
    filename_predicted: str | None = None
    output_path: str | None = None
    error: str | None = None
    merged_from: list[str] = Field(default_factory=list)
    fps: float | None = None
    resolution: str | None = None
    codec: str | None = None
    bitrate: int | None = None
    filesize_mb: float | None = None
    last_updated: datetime | None = None

    class Config:
        extra = "ignore"


# ------------------------------------------------------------
# 🧱 BASE COMMUNE (standard & lite)
# ------------------------------------------------------------
class SmartcutSessionBase(BaseModel):
    video: str
    video_name: str
    uid: str
    duration: float
    origin: str | None = "smartcut"
    fps: float | None = None
    resolution: str | None = None
    codec: str | None = None
    bitrate: int | None = None
    filesize_mb: float | None = None
    created_at: datetime | None = None
    last_updated: datetime | None = None
    status: str | None = "cut"
    segments: list[SmartcutSegment] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    class Config:
        extra = "ignore"


# ------------------------------------------------------------
# 🧠 Détection automatique + validation
# ------------------------------------------------------------


def parse_smartcut_json(data: dict[str, Any], filename: str) -> tuple[bool, SmartcutSessionBase, str, str]:
    """
    Valide une session Smartcut (standard ou lite, distinction via origin).
    """
    try:
        # --- Validation générique
        session = SmartcutSessionBase(**data)
        session_type = session.origin.replace("smartcut_", "") if session.origin else "unknown"

        # --- Validation du statut
        if session.status not in ("smartcut_done", "cut"):
            return False, session, session_type, f"status={session.status}"

        # --- Auto-remplissage du nom si besoin
        if not session.video_name and session.video:
            from pathlib import Path

            session.video_name = Path(session.video).stem

        logger.debug(
            "✅ JSON %s détecté (%s) → origin=%s, video=%s, name=%s",
            filename,
            session_type,
            session.origin,
            session.video,
            session.video_name,
        )

        return True, session, session_type, ""

    except ValidationError as err:
        logger.warning("❌ Erreur validation JSON %s : %s", filename, err)
        return False, session, "unknown", str(err)


if TYPE_CHECKING:
    from cutmind.models.smartcut_parser import SmartcutSessionBase


# -------------------------------------------------------------------
# 🔄 Conversion SmartCut → Video (objet DB unifié)
# -------------------------------------------------------------------
def convert_json_to_video(session: SmartcutSessionBase) -> Video:
    """
    Convertit une session SmartCut (standard ou lite) en objet Video complet.

    Cette fonction est la passerelle entre le monde SmartCut (JSON)
    et le monde CutMind (base de données + objets Python).

    Args:
        session: instance SmartcutSessionBase issue de parse_smartcut_json()

    Returns:
        Video : objet prêt à être inséré en base via CutMindRepository
    """
    video = Video(
        uid=session.uid,
        name=session.video_name or Path(session.video).stem,
        duration=session.duration,
        fps=session.fps,
        resolution=session.resolution,
        codec=session.codec,
        bitrate=session.bitrate,
        filesize_mb=session.filesize_mb,
        status=session.status or "init",
        origin=session.origin or "smartcut",
    )

    # --- Conversion des segments ---
    for s in session.segments:
        seg = Segment(
            uid=s.uid,
            start=s.start,
            end=s.end,
            duration=s.duration,
            status="raw",
            confidence=s.confidence,
            description=s.description,
            fps=s.fps or session.fps,
            resolution=s.resolution or session.resolution,
            codec=s.codec or session.codec,
            bitrate=s.bitrate or session.bitrate,
            filesize_mb=s.filesize_mb,
            filename_predicted=s.filename_predicted,
            output_path=s.output_path,
            source_flow=session.origin or "smartcut",
            keywords=s.keywords or [],
        )
        video.segments.append(seg)

    return video
