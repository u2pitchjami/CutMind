""" """

from __future__ import annotations

from pathlib import Path
import subprocess

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx


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
    Désentrelace une vidéo en utilisant yadif CPU (fiable à 100%).
    """
    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-vf",
            "yadif",
            "-c:v",
            "libx265",
            "-preset",
            "slow",
            "-crf",
            "17",
            "-c:a",
            "copy",
            str(output_path),
        ]

        subprocess.run(cmd, check=True)
        return True

    except subprocess.CalledProcessError as e:
        raise CutMindError(
            "❌ Erreur FFMPEG lors du désentrelacement.",
            code=ErrCode.FFMPEG,
            ctx=get_step_ctx({"video_path": str(input_path)}),
        ) from e

    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors du désentrelacement.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video_path": str(input_path)}),
        ) from exc
