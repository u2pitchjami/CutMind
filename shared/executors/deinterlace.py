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


def deinterlace_video(input_path: Path, output_path: Path, use_cuda: bool = False) -> bool:
    """
    Désentrelace une vidéo (CPU ou GPU selon l’option).
    """
    try:
        filter_type = "yadif_cuda" if use_cuda else "yadif"
        codec = "hevc_nvenc" if use_cuda else "libx265"
        cmd = [
            "ffmpeg",
            "-y",
            "-hwaccel",
            "cuda" if use_cuda else "auto",
            "-i",
            str(input_path),
            "-vf",
            filter_type,
            "-c:v",
            codec,
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
            "❌ Erreur FFMPEG lors du deinterlace de la vidéo.",
            code=ErrCode.FFMPEG,
            ctx=get_step_ctx({"video_path": str(input_path)}),
        ) from e
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors du deinterlace de la vidéo.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video_path": str(input_path)}),
        ) from exc
