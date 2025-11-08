from cutmind.db.repository import CutMindRepository
from cutmind.imports.validation import analyze_session_validation_db
from shared.utils.config import MIN_CONFIDENCE
from shared.utils.logger import get_logger

logger = get_logger(__name__)


def revalidate_manual_videos(min_confidence: float = MIN_CONFIDENCE) -> None:
    """
    Relance la validation automatique sur toutes les vidéos en 'manual_review'.

    Args:
        min_confidence: seuil minimal pour valider automatiquement les segments.
    """
    repo = CutMindRepository()
    videos = repo.get_videos_by_status("manual_review")

    if not videos:
        logger.info("✅ Aucune vidéo à revalider (manual_review).")
        return

    logger.info("🔁 Relance de validation pour %d vidéos.", len(videos))

    for video in videos:
        try:
            result = analyze_session_validation_db(video=video, min_confidence=min_confidence)
            logger.info(
                "🎬 Revalidation : %s | valid=%d/%d | auto_valid=%s",
                result["uid"],
                result["valid"],
                result["total"],
                result["auto_valid"],
            )
        except Exception as err:
            logger.error("❌ Erreur revalidation vidéo %s : %s", getattr(video, "uid", "?"), err)
