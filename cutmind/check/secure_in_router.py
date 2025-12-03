# check/check_enhanced_segments.py


from cutmind.db.repository import CutMindRepository
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger


@with_child_logger
def check_secure_in_router(logger: LoggerProtocol | None = None) -> None:
    logger = ensure_logger(logger, __name__)
    repo = CutMindRepository()
    try:
        videos = repo.get_videos_by_status("processing_router")
        modified_count = 0
        logger.info(f"▶️ videos avec le statut processing_router : {len(videos)}")
        for video in videos:
            logger.info("▶️ processing_router : %s", video.name)
            for seg in video.segments:
                if seg.status != "in_router":
                    logger.debug("🛑 segment non modifié  :  %s", seg.status)
                    continue
                seg.status = "validated"
                repo.update_segment_validation(seg)
                logger.info("✅ Segment mis à jour : %s", seg.uid)
                modified_count += 1

            video.status = "validated"
            repo.update_video(video)

        logger.info("✔️ Vérification Secure in Router terminée. %d segments mis à jour.", modified_count)
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors de check_secure_in_router.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video": video.name, "segment_id": seg.id}),
        ) from exc
