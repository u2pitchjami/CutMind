""" """

from __future__ import annotations

from pathlib import Path
import subprocess

from shared.ffmpegjob.ffjob import FFmpegJob, run_ffmpeg_job
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.logger import LoggerProtocol


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


def deinterlace_video(
    input_path: Path,
    output_path: Path,
    has_audio: bool = True,
    logger: LoggerProtocol | None = None,
) -> Path:
    """
    Désentrelace une vidéo avec yadif CPU et export normalisé CutMind.
    """

    return run_ffmpeg_job(
        FFmpegJob(
            step="deinterlace_video",
            input_path=input_path,
            output_path=output_path,
            include_audio=has_audio,
            video_filters=["yadif"],
        ),
        logger=logger,
    )
