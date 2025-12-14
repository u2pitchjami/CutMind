""" """

from __future__ import annotations

from pathlib import Path
import subprocess

from shared.executors.ffmpeg_utils import detect_nvenc_available
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx


def convert_to_60fps(input_path: Path, output_path: Path) -> bool:
    """
    Convertit une vidéo à 60 FPS en H.265, avec détection auto GPU/CPU.

    - Utilise hevc_nvenc (GPU) si disponible, sinon libx265 (CPU)
    - GPU : mode CQ (qualité constante)
    - CPU : mode CRF (qualité constante)
    """
    use_nvenc = detect_nvenc_available()

    # Sélection des paramètres selon le mode
    if use_nvenc:
        codec = "hevc_nvenc"
        preset = "p6"
        quality_args = ["-cq", "17", "-rc", "vbr", "-b:v", "0"]
        hwaccel = ["-hwaccel", "cuda"]
    else:
        codec = "libx265"
        preset = "slow"
        quality_args = ["-crf", "17"]
        hwaccel = []

    cmd = [
        "ffmpeg",
        "-y",  # overwrite sans confirmation
        *hwaccel,
        "-i",
        str(input_path),
        "-r",
        "60",
        "-c:v",
        codec,
        "-preset",
        preset,
        *quality_args,
        "-c:a",
        "copy",
        str(output_path),
    ]
    try:
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError as err:
        raise CutMindError(
            "❌ Erreur FFprobe lors de la de la conversion 60 fps.",
            code=ErrCode.FFMPEG,
            ctx=get_step_ctx({"video_path": input_path}),
        ) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur innatendue lors de la de la conversion 60 fps.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video_path": input_path}),
        ) from exc
