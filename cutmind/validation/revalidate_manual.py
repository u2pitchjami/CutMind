""" """

from __future__ import annotations

from cutmind.db.repository import CutMindRepository
from cutmind.validation.validation import analyze_session_validation_db
from shared.utils.config import MIN_CONFIDENCE
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger


@with_child_logger
def revalidate_manual_videos(min_confidence: float = MIN_CONFIDENCE, logger: LoggerProtocol | None = None) -> None:
    """
    Relance la validation automatique sur toutes les vidéos en 'manual_review'.

    Args:
        min_confidence: seuil minimal pour valider automatiquement les segments.
    """
    logger = ensure_logger(logger, __name__)
    repo = CutMindRepository()
    videos = repo.get_videos_by_status("manual_review")

    if not videos:
        logger.info("✅ Aucune vidéo à revalider (manual_review).")
        return

    logger.info("🔁 Relance de validation pour %d vidéos.", len(videos))

    for video in videos:
        try:
            result = analyze_session_validation_db(video=video, min_confidence=min_confidence, logger=logger)
            logger.info(
                "🎬 Revalidation : %s | valid=%d/%d | auto_valid=%s",
                result["uid"],
                result["valid"],
                result["total"],
                result["auto_valid"],
            )
        except Exception as err:
            logger.error("❌ Erreur revalidation vidéo %s : %s", getattr(video, "uid", "?"), err)
