""" """

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from shared.executors.ffmpeg_utils import detect_nvenc_available
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx


def get_total_frames(video_path: Path) -> int:
    """
    Retourne le nombre total de frames d'une vidéo via ffprobe.
    """
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_frames,avg_frame_rate,duration",
            "-of",
            "json",
            str(video_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        stream = data.get("streams", [{}])[0]

        # Si nb_frames est directement disponible
        if "nb_frames" in stream and stream["nb_frames"].isdigit():
            return int(stream["nb_frames"])

        # Sinon, on estime via duration * avg_frame_rate
        if "duration" in stream and "avg_frame_rate" in stream:
            rate_num, rate_den = map(int, stream["avg_frame_rate"].split("/"))
            duration = float(stream["duration"])
            return int(duration * (rate_num / rate_den))
        return 0
    except subprocess.CalledProcessError as err:
        raise CutMindError(
            "❌ Erreur FFprobe lors de la détection du nb de frames.",
            code=ErrCode.FFMPEG,
            ctx=get_step_ctx({"video_path": video_path}),
        ) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur innatendue lors de la détection du nb de frames.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video_path": video_path}),
        ) from exc


def video_has_audio(video_path: Path) -> bool:
    """
    Retourne True si la vidéo contient une piste audio (via ffprobe).
    """
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=index",
                "-of",
                "csv=p=0",
                str(video_path),
            ],
            capture_output=True,
            text=True,
        )
        return bool(result.stdout.strip())
    except subprocess.CalledProcessError as err:
        raise CutMindError(
            "❌ Erreur FFprobe lors de la détection de l'audio.",
            code=ErrCode.FFMPEG,
            ctx=get_step_ctx({"video_path": video_path}),
        ) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur innatendue lors de la détection de l'audio.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video_path": video_path}),
        ) from exc


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
