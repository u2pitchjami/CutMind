# check/check_status.py


from cutmind.db.repository import CutMindRepository
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from shared.utils.settings import get_settings


@with_child_logger
def check_video_segment_status(
    video_status: str, expected_segment_statuses: list[str], logger: LoggerProtocol | None = None
) -> None:
    """
    Exécute une règle de cohérence entre le statut d'une vidéo et ses segments.
    Loggue les incohérences détectées.
    """
    logger = ensure_logger(logger, __name__)
    repo = CutMindRepository()
    try:
        rows = repo.get_segments_status_mismatch(video_status, expected_segment_statuses)
        if not rows:
            logger.info(f"✅ Vidéo status = '{video_status}' : aucun écart détecté.")
            return

        logger.warning(f"⚠️ {len(rows)} incohérences détectées pour video.status = '{video_status}'")

        for row in rows:
            logger.warning(
                f" - Video {row['video_id']} ({row['filename']}) / Segment {row['segment_id']} "
                f"=> segment.status = '{row['segment_status']}' (attendu: {expected_segment_statuses})"
            )
    except CutMindError as err:
        raise err.with_context(get_step_ctx({"video_status": video_status})) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur lors du Check Status.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video_status": video_status}),
        ) from exc


@with_child_logger
def check_all_video_segment_status_rules(logger: LoggerProtocol | None = None) -> None:
    logger = ensure_logger(logger, __name__)
    try:
        settings = get_settings()
        rules = settings.cutmind_status_consistency

        for video_status, expected_segment_statuses in rules.__dict__.items():
            check_video_segment_status(video_status, expected_segment_statuses, logger=logger)

    except CutMindError as err:
        raise err.with_context(get_step_ctx()) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur lors du Check Status.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx(),
        ) from exc
