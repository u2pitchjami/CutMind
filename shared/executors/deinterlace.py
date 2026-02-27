""" """

from __future__ import annotations

from pathlib import Path
import subprocess

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.settings import get_settings


def is_interlaced(video_path: Path) -> str:
    """
    Retourne True si la vidéo est entrelacée.
    """
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=field_order",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        field_order = result.stdout.strip().lower()
        return field_order
    except subprocess.CalledProcessError as e:
        raise CutMindError(
            "❌ Erreur FFMPEG lors du test deinterlace.",
            code=ErrCode.FFMPEG,
            ctx=get_step_ctx({"video_path": str(video_path)}),
        ) from e
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors du test deinterlace.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video_path": str(video_path)}),
        ) from exc


def deinterlace_video(input_path: Path, output_path: Path) -> bool:
    """
    Désentrelace une vidéo en utilisant yadif CPU, avec normalisation cohérente CutMind.
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

    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-vf",
            "yadif",
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

        subprocess.run(cmd, check=True)
        return True

    except subprocess.CalledProcessError as exc:
        raise CutMindError(
            "❌ Erreur FFMPEG lors du désentrelacement.",
            code=ErrCode.FFMPEG,
            ctx=get_step_ctx({"video_path": str(input_path)}),
        ) from exc

    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors du désentrelacement.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video_path": str(input_path)}),
        ) from exc
