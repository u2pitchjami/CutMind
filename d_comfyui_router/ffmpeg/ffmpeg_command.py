""" """

from __future__ import annotations

from pathlib import Path
import subprocess

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.settings import get_settings


def convert_to_60fps(input_path: Path, output_path: Path) -> Path:
    """
    Force une vidéo à 60 FPS en respectant le profil interne CutMind.
    """
    settings = get_settings()

    PRESET: str = settings.ffsmartcut.preset
    VCODEC: str = settings.ffsmartcut.vcodec
    CRF: int = settings.ffsmartcut.crf
    PIX_FMT: str = settings.ffsmartcut.pix_fmt
    PROFILE: str = settings.ffsmartcut.profile
    COLOR_PRIMARIES: str = settings.ffsmartcut.color_primaries
    COLOR_TRC: str = settings.ffsmartcut.color_trc
    COLORSPACE: str = settings.ffsmartcut.colorspace
    VSYNC: str = settings.ffsmartcut.vsync
    TAG: str = settings.ffsmartcut.tag
    MOVFLAGS: str = settings.ffsmartcut.movflags
    ACODEC: str = settings.ffsmartcut.acodec
    AUDIO_BITRATE: str = settings.ffsmartcut.audio_bitrate
    AR: int = settings.ffsmartcut.ar
    AC: int = settings.ffsmartcut.ac

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-vf",
        "fps=60",
        "-c:v",
        VCODEC,
        "-preset",
        PRESET,
        "-crf",
        str(CRF),
        "-pix_fmt",
        PIX_FMT,
        "-profile:v",
        PROFILE,
        "-color_primaries",
        COLOR_PRIMARIES,
        "-color_trc",
        COLOR_TRC,
        "-colorspace",
        COLORSPACE,
        "-vsync",
        VSYNC,
        "-tag:v",
        TAG,
        "-movflags",
        MOVFLAGS,
        "-c:a",
        ACODEC,
        "-b:a",
        AUDIO_BITRATE,
        "-ar",
        str(AR),
        "-ac",
        str(AC),
        str(output_path),
    ]

    try:
        subprocess.run(cmd, check=True)
        return output_path

    except subprocess.CalledProcessError as err:
        raise CutMindError(
            "❌ Erreur FFmpeg lors de la conversion à 60 FPS.",
            code=ErrCode.FFMPEG,
            ctx=get_step_ctx({"video_path": str(input_path)}),
        ) from err

    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors de la conversion à 60 FPS.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video_path": str(input_path)}),
        ) from exc
