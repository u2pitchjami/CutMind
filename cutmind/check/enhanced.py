# check/check_enhanced_segments.py

from pathlib import Path
import random

from pymediainfo import MediaInfo

from cutmind.db.repository import CutMindRepository
from cutmind.services.categ.categ_serv import match_category
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger


@with_child_logger
def check_enhanced_segments(max_videos: int = 10, logger: LoggerProtocol | None = None) -> None:
    logger = ensure_logger(logger, __name__)
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
            if seg.status != "enhanced":
                logger.debug("🛑 segment non enrichi  :  %s", seg.status)
                continue

            path = Path(seg.output_path or "")
            if not path.exists():
                logger.warning("🛑 Fichier manquant : %s", path)
                continue

            try:
                media_info = MediaInfo.parse(str(path))
                for track in media_info.tracks:
                    if track.track_type == "Video":
                        updated = False

                        new_res = f"{track.width}x{track.height}"
                        if seg.resolution != new_res:
                            seg.resolution = new_res
                            updated = True

                        if seg.codec != track.codec:
                            seg.codec = track.codec
                            updated = True

                        if seg.bitrate != track.bit_rate:
                            seg.bitrate = track.bit_rate
                            updated = True

                        size_mb = round(path.stat().st_size / (1024 * 1024), 2)
                        if seg.filesize_mb != size_mb:
                            seg.filesize_mb = size_mb
                            updated = True

                        dur = round(track.duration / 1000, 3) if track.duration else None
                        if seg.duration != dur:
                            seg.duration = dur
                            updated = True

                        fps = float(track.frame_rate) if track.frame_rate else None
                        if seg.fps != fps:
                            seg.fps = fps
                            updated = True

                        if updated:
                            seg.status = "enhanced"
                            seg.category = match_category(seg.keywords, logger=logger)
                            repo.update_segment_postprocess(seg)
                            logger.info("✅ Segment mis à jour : %s", seg.uid)
                            modified_count += 1

            except Exception as exc:
                raise CutMindError(
                    "❌ Erreur inattendue lors de check_enhanced.",
                    code=ErrCode.UNEXPECTED,
                    ctx=get_step_ctx({"video": video.name, "segment_id": seg.id}),
                ) from exc

    logger.info("✔️ Vérification terminée. %d segments mis à jour.", modified_count)
