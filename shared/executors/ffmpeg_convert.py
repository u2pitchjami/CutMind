"""
Commandes ffmpeg pour smartcut.
"""

from __future__ import annotations

import ffmpeg  # type: ignore

from shared.models.exceptions import CutMindError, ErrCode
from shared.utils.settings import get_settings


def convert_safe_video_format(video_path: str, output_path: str) -> None:
    """
    Normalize video to CutMind internal standard (HEVC / yuv420p / bt709 / CFR).
    """
    settings = get_settings()
    PRESET = settings.ffsmartcut.preset
    PIX_FMT = settings.ffsmartcut.pix_fmt
    VCODEC = settings.ffsmartcut.vcodec
    CRF = settings.ffsmartcut.crf
    PROFILE = settings.ffsmartcut.profile
    COLOR_PRIMARIES = settings.ffsmartcut.color_primaries
    COLOR_TRC = settings.ffsmartcut.color_trc
    COLORSPACE = settings.ffsmartcut.colorspace
    VSYNC = settings.ffsmartcut.vsync
    TAG = settings.ffsmartcut.tag
    MOVFLAGS = settings.ffsmartcut.movflags
    ACODEC = settings.ffsmartcut.acodec
    AUDIO_BITRATE = settings.ffsmartcut.audio_bitrate
    AR = settings.ffsmartcut.ar
    AC = settings.ffsmartcut.ac
    try:
        (
            ffmpeg.input(video_path)
            .output(
                output_path,
                vcodec=VCODEC,
                preset=PRESET,
                crf=CRF,
                pix_fmt=PIX_FMT,
                profile=PROFILE,
                color_primaries=COLOR_PRIMARIES,
                color_trc=COLOR_TRC,
                colorspace=COLORSPACE,
                vsync=VSYNC,
                tag=TAG,
                movflags=MOVFLAGS,
                acodec=ACODEC,
                audio_bitrate=AUDIO_BITRATE,
                ar=AR,
                ac=AC,
            )
            .overwrite_output()
            .run(quiet=True)
        )

    except ffmpeg.Error as exc:
        raise CutMindError(
            "[FFMPEG] ❌ Erreur dans la normalisation vidéo",
            code=ErrCode.FFMPEG,
            ctx={"step": "convert_safe_video_format", "video_path": video_path},
            original_exception=exc,
        ) from exc
