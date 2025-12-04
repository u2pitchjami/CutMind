# check/check_enhanced_segments.py

from pathlib import Path

from cutmind.models_cm.db_models import Segment
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.services.video_preparation import get_video_metadata_all


def check_segments(seg: Segment, path: Path) -> bool:
    updated = False
    try:
        metadata = get_video_metadata_all(video_path=path)

        if seg.resolution != metadata.resolution:
            seg.resolution = metadata.resolution
            updated = True

        if seg.codec != metadata.codec:
            seg.codec = metadata.codec
            updated = True

        if seg.bitrate != metadata.bitrate:
            seg.bitrate = metadata.bitrate
            updated = True

        if seg.filesize_mb != metadata.filesize_mb:
            seg.filesize_mb = metadata.filesize_mb
            updated = True

        if seg.duration != metadata.duration:
            seg.duration = metadata.duration
            updated = True

        if seg.fps != metadata.fps:
            seg.fps = metadata.fps
            updated = True

        return updated
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors de check_enhanced.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"seg.id": seg.id, "path": seg.id}),
        ) from exc
