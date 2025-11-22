# check/check_enhanced_segments.py

from datetime import datetime

from cutmind.db.repository import CutMindRepository
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger


@with_child_logger
def check_secure_in_router(logger: LoggerProtocol | None = None) -> None:
    logger = ensure_logger(logger, __name__)
    repo = CutMindRepository()
    videos = repo.get_videos_by_status("processing_router", logger=logger)
    modified_count = 0
    logger.info(f"▶️ videos avec le statut processing_router : {len(videos)}")
    for video in videos:
        logger.info("▶️ processing_router : %s", video.name)
        for seg in video.segments:
            if seg.status != "in_router":
                logger.debug("🛑 segment non modifié  :  %s", seg.status)
                continue
            try:
                seg.last_updated = datetime.now()
                seg.status = "validated"
                repo.update_segment_validation(seg, logger=logger)
                logger.info("✅ Segment mis à jour : %s", seg.uid)
                modified_count += 1
            except Exception as exc:
                logger.error("❌ Erreur sur %s : %s", seg.enhanced_path, exc)
        video.status = "validated"
        repo.update_video(video, logger=logger)

    logger.info("✔️ Vérification Secure in Router terminée. %d segments mis à jour.", modified_count)
