"""
Commandes ffmpeg pour smartcut.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger

# ========== Utils FFprobe/FFmpeg ==========


@with_child_logger
def get_duration(video_path: Path, logger: LoggerProtocol | None = None) -> float:
    """
    Retourne la durée en secondes (0.0 si échec).
    """
    logger = ensure_logger(logger, __name__)
    cmd: list[str] = [
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
        out = subprocess.check_output(cmd).decode().strip()
        return float(out)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("ffprobe duration error: %s", exc)
        return 0.0


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
