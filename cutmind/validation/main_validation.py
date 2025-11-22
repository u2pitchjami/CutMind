# check/check_enhanced_segments.py

from cutmind.db.repository import CutMindRepository
from cutmind.validation.validation import analyze_session_validation_db
from shared.utils.config import MIN_CONFIDENCE
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger


@with_child_logger
def validation(logger: LoggerProtocol | None = None) -> None:
    logger = ensure_logger(logger, __name__)
    repo = CutMindRepository()
    videos = repo.get_videos_by_status("smartcut_done", logger=logger)
    auto_valid_count = 0
    manual_valid_count = 0
    logger.info("⭐ Lancement de la Validation")
    logger.info(f"▶️ videos avec le statut smartcut_done : {len(videos)}")
    for video in videos:
        logger.info("▶️ Tentative de validation pour : %s", video.name)
        # --- Validation automatique ---
        try:
            result = analyze_session_validation_db(video=video, min_confidence=MIN_CONFIDENCE, logger=logger)
            auto_valid = result["auto_valid"]
            valid = result["valid"]
            total = result["total"]
            moved = result["moved"]

            if auto_valid:
                logger.info("🎯 Auto-validation complète (%d/%d segments)", valid, total)
                if moved:
                    logger.info("🔀 Fichiers vidéo déplacés pour %s", video.uid)
                    auto_valid_count += 1
                else:
                    logger.warning("ℹ️ Fichiers vidéo non déplacés pour %s", video.uid)
                    raise Exception("Échec du déplacement")
            else:
                logger.info("🕵️ Validation manuelle requise (%d/%d segments)", valid, total)
                manual_valid_count += 1
        except Exception as exc:
            logger.error("❌ Erreur sur %s : %s", video.name, exc)

    logger.info(
        f"✔️ Validation terminée : {auto_valid_count} auto validées, {manual_valid_count}\
            à valider manuellement sur {len(videos)} vidéos"
    )
