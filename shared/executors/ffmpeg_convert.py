"""
Commandes ffmpeg pour smartcut.
"""

from __future__ import annotations

import ffmpeg  # type: ignore

from shared.models.exceptions import CutMindError, ErrCode
from shared.utils.settings import get_settings

settings = get_settings()
PRESET = settings.ffsmartcut.preset
RC = settings.ffsmartcut.rc
CQ = settings.ffsmartcut.cq
PIX_FMT = settings.ffsmartcut.pix_fmt
VCODEC = settings.ffsmartcut.vcodec


def convert_safe_video_format(video_path: str, output_path: str) -> None:
    """
    convert video to safe format
    """
    try:
        ffmpeg.input(video_path).output(
            str(output_path),
            vcodec=VCODEC,
            preset=PRESET,
            rc=RC,
            cq=CQ,
            pix_fmt=PIX_FMT,
        ).run(quiet=True, overwrite_output=True)
    except Exception as exc:
        raise CutMindError(
            "[FFMPEG] ❌ Erreur dans la conversion de la vidéo",
            code=ErrCode.FFMPEG,
            ctx={"step": "convert_safe_video_format", "video_path": video_path},
        ) from exc
