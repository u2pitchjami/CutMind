"""
Commandes ffmpeg pour smartcut.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from shared.models.exceptions import CutMindError, ErrCode
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger

# ========== Utils FFprobe/FFmpeg ==========


def get_duration(video_path: Path) -> float:
    """
    Retourne la durée en secondes.
    - Lève CutMindError(code=BADFORMAT) si le fichier n'est pas une vidéo
    - Lève CutMindError(code=FFMPEG) en cas d'erreur technique ffprobe
    - Lève CutMindError(code=UNEXPECTED) pour toute erreur Python inattendue
    """

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]

    try:
        output = (
            subprocess.check_output(
                cmd,
                stderr=subprocess.STDOUT,  # capture la sortie erreur de ffprobe
            )
            .decode(errors="ignore")
            .strip()
        )

        return float(output)

    except subprocess.CalledProcessError as exc:
        # ffprobe a échoué → analysons la sortie
        ffout = exc.output.decode(errors="ignore")

        # 🟥 Cas 1 : Fichier non vidéo / format illisible
        if (
            "Invalid data" in ffout
            or "Invalid argument" in ffout
            or "moov atom" in ffout
            or "could not find codec parameters" in ffout.lower()
        ):
            raise CutMindError(
                "Fichier non vidéo ou format illisible.",
                code=ErrCode.BADFORMAT,
                ctx={
                    "video_path": str(video_path),
                    "ffprobe_output": ffout,
                },
            ) from exc

        # 🟧 Cas 2 : Erreur technique ffmpeg (codec, lib, etc.)
        raise CutMindError(
            "Erreur technique FFmpeg lors de la récupération de la durée.",
            code=ErrCode.FFMPEG,
            ctx={
                "video_path": str(video_path),
                "ffprobe_output": ffout,
            },
        ) from exc

    except ValueError as exc:
        # ffprobe a renvoyé une durée vide ou non convertible
        raise CutMindError(
            "FFmpeg a renvoyé une durée invalide.",
            code=ErrCode.FFMPEG,
            ctx={"video_path": str(video_path), "output": output},
        ) from exc

    except Exception as exc:
        # 🟦 Cas 3 : erreur Python inattendue
        raise CutMindError(
            "Erreur inattendue lors de la récupération de durée.",
            code=ErrCode.UNEXPECTED,
            ctx={"video_path": str(video_path)},
        ) from exc


def get_resolution(filepath: Path) -> tuple[int, int]:
    """
    Retourne la largeur et hauteur de la vidéo via ffprobe.
    """
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(filepath),
        ]
        result = subprocess.check_output(cmd)
        info = json.loads(result)
        w = info["streams"][0]["width"]
        h = info["streams"][0]["height"]
        return w, h
    except Exception:
        return 0, 0


def get_fps(filepath: Path) -> float:
    """
    Retourne le framerate de la vidéo.
    """
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=r_frame_rate",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(filepath),
        ]
        output = subprocess.check_output(cmd).decode().strip()
        num, den = map(int, output.split("/"))
        return num / den if den else float(num)
    except Exception:
        return 0.0


@with_child_logger
def detect_nvenc_available(logger: LoggerProtocol | None = None) -> bool:
    """
    Vérifie si l'encodeur NVIDIA NVENC (hevc_nvenc) est disponible.
    """
    logger = ensure_logger(logger, __name__)
    try:
        result = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, check=True)
        return "hevc_nvenc" in result.stdout
    except subprocess.CalledProcessError:
        logger.warning("⚠️ Impossible de détecter les encodeurs FFmpeg.")
        return False
