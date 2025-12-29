# check/check_enhanced_segments.py

from cutmind.db.repository import CutMindRepository
from cutmind.executors.validation import analyze_session_validation_db
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.models.timer_manager import Timer
from shared.utils.config import MIN_CONFIDENCE
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from shared.utils.settings import get_settings

settings = get_settings()


@with_child_logger
def validation(manual: bool = False, logger: LoggerProtocol | None = None) -> None:
    logger = ensure_logger(logger, __name__)
    STATUS = settings.cutmind_validation.manual if manual else settings.cutmind_validation.normal
    repo = CutMindRepository()
    try:
        videos = repo.get_videos_by_status(STATUS)
        auto_valid_count = 0
        manual_valid_count = 0
        logger.info("⭐ Lancement de la Validation")
        logger.info(f"▶️ videos avec le statut {STATUS} : {len(videos)}")
        for video in videos:
            logger.info("▶️ Tentative de STATUS pour : %s", video.name)
            # --- Validation automatique ---
            try:
                with Timer(f"Traitement de Validation : {video.name}", logger):
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
                        raise CutMindError(
                            "❌ Erreur innatendue lors de la validation : Échec du déplacement.",
                            code=ErrCode.UNEXPECTED,
                            ctx=get_step_ctx({"name": video.name}),
                        )
                else:
                    logger.info("🕵️ Validation manuelle requise (%d/%d segments)", valid, total)
                    manual_valid_count += 1
            except Exception as exc:
                logger.error("❌ Erreur sur %s : %s", video.name, exc)

        logger.info(
            f"✔️ Validation terminée : {auto_valid_count} auto validées, {manual_valid_count}\
                à valider manuellement sur {len(videos)} vidéos"
        )
    except CutMindError as err:
        raise err.with_context(get_step_ctx({"name": video.name, "manual": manual})) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur innatendue lors de la validation.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"name": video.name, "manual": manual}),
        ) from exc
