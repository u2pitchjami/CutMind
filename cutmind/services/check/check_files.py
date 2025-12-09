# check/check_enhanced_segments.py

from pathlib import Path
import random

from cutmind.db.repository import CutMindRepository
from cutmind.executors.check.enhanced import check_segments
from cutmind.executors.check.log_metadata_diff import log_metadata_diff
from cutmind.services.categ.categ_serv import match_category
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.services.video_preparation import get_metadata_all
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger


@with_child_logger
def check_enhanced_segments(max_videos: int = 10, logger: LoggerProtocol | None = None) -> None:
    logger = ensure_logger(logger, __name__)
    logger.info("💫 Démarrage du check_enhanced_segments.")
    repo = CutMindRepository()
    videos = repo.get_videos_by_status("enhanced")
    if not videos:
        logger.info("No enhanced videos found for checking.")
        return
    random.shuffle(videos)
    selected = videos[:max_videos]
    modified_count = 0
    logger.info(f"▶️ videos : {len(selected)}")
    for video in selected:
        logger.info("▶️ check_enhanced : %s", video.name)
        for seg in video.segments:
            if not seg or not seg.id:
                continue
            if seg.status != "enhanced":
                logger.debug("🛑 segment non enrichi  :  %s", seg.status)
                continue

            path = Path(seg.output_path or "")
            if not path.exists():
                logger.warning("🛑 Fichier manquant : %s", path)
                continue

            try:
                metadata = get_metadata_all(video_path=path)
                updated = check_segments(seg, metadata, path)

                if updated:
                    log_metadata_diff(seg, metadata, logger)
                    seg.status = "enhanced"
                    seg.category = match_category(seg.keywords, logger=logger)
                    repo.update_segment_from_metadata(segment_id=seg.id, metadata=metadata)
                    repo.update_segment_validation(seg)
                    logger.info("✅ Segment mis à jour : %s", seg.uid)
                    modified_count += 1

            except Exception as exc:
                raise CutMindError(
                    "❌ Erreur inattendue lors de check_enhanced.",
                    code=ErrCode.UNEXPECTED,
                    ctx=get_step_ctx({"video": video.name, "segment_id": seg.id}),
                ) from exc

    logger.info("✔️ Vérification terminée. %d segments mis à jour.", modified_count)
