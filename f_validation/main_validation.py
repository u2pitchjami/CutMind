# check/check_enhanced_segments.py

from f_validation.validation import validation_cut, validation_db
from shared.models.db_models import Segment, Video
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.models.timer_manager import Timer
from shared.status_orchestrator.statuses import SegmentStatus
from shared.utils.config import MIN_CONFIDENCE
from shared.utils.logger import get_logger


def validation(
    vid: Video,
    segments: list[Segment],
    status: str = SegmentStatus.CONFIDENCE_DONE,
) -> None:
    logger = get_logger("CutMind-Validation")
    logger.info("🚀 Démarrage de la Validation")
    logger.info("🎞️ Vidéo '%s' nb segments: %i", vid.name, len(segments))
    try:
        logger.info("⭐ Lancement de la Validation pour %d segment de : %s", len(segments), vid.name)
        # --- Validation automatique ---
        try:
            with Timer(f"Traitement de Validation : {vid.name}", logger):
                if status == SegmentStatus.CONFIDENCE_DONE:
                    result = validation_db(video=vid, segments=segments, min_confidence=MIN_CONFIDENCE, logger=logger)
                else:
                    result = validation_cut(video=vid, segments=segments, min_confidence=MIN_CONFIDENCE, logger=logger)

                valid = result["valid"]
                ia_return = result["ia_return"]
                total = result["total"]
                # moved = result["moved"]
                manual_valid = result["total"] - valid - ia_return

            if valid:
                logger.info("🎯 Auto-validation (%d/%d segments)", valid, total)
                # if moved:
                #     logger.info("🔀 %d Segments déplacés pour %s", len(moved))
                #     valid_count += 1
                # else:
                #     no_moved_count = total - valid
                #     logger.warning("ℹ️ %d Segments non déplacés pour %s", len(no_moved_count))
                # raise CutMindError(
                #     "❌ Erreur innatendue lors de la validation : Échec du déplacement.",
                #     code=ErrCode.UNEXPECTED,
                #     ctx=get_step_ctx({"name": video.name}),
                # )
            if manual_valid:
                logger.info("🕵️ Validation manuelle requise (%d/%d segments)", manual_valid, total)
            if ia_return:
                logger.info("🤖 Validation IA requise (%d/%d segments)", ia_return, total)
        except Exception as exc:
            logger.error("❌ Erreur sur %s : %s", vid.name, exc)

        logger.info(
            f"✔️ Validation terminée : {valid} segments validés,\
{ia_return} segments à valider par l'IA,\
{manual_valid} à valider manuellement"
        )
    except CutMindError as err:
        raise err.with_context(get_step_ctx({"name": vid.name, "status": status})) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur innatendue lors de la validation.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"name": vid.name, "status": status}),
        ) from exc
