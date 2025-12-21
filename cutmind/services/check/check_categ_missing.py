# check/check_status.py


from cutmind.db.repository import CutMindRepository
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger


@with_child_logger
def check_segments_missing_category(
    expected_statuses: list[str] | None = None,
    logger: LoggerProtocol | None = None,
) -> None:
    """
    Vérifie que les segments validés ou améliorés ont bien une catégorie.
    Loggue les incohérences détectées.
    """
    logger = ensure_logger(logger, __name__)
    repo = CutMindRepository()
    try:
        if expected_statuses is None:
            expected_statuses = ["validated", "enhanced"]

        segments = repo.get_segments_by_category(category=None, expected_segment_statuses=expected_statuses)

        if not segments:
            logger.info(f"✅ Aucun segment en {expected_statuses} sans catégorie.")
            return

        logger.warning(f"⚠️ {len(segments)} segments en {expected_statuses} sans catégorie (NULL)")

        for s in segments:
            logger.warning(f" - Segment {s.id} (video_id: {s.video_id}) → status = {s.status}, category = None")
    except CutMindError as err:
        raise err.with_context(get_step_ctx()) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur dans check_segments_missing_category.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx(),
        ) from exc
