"""
Commandes ffmpeg pour smartcut.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from shared.models.exceptions import CutMindError, ErrCode

# ========== Utils FFprobe/FFmpeg ==========


def get_duration(video_path: Path) -> float:
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
                stderr=subprocess.STDOUT,
            )
            .decode(errors="ignore")
            .strip()
        )

        duration = float(output)
        return duration

    except subprocess.CalledProcessError as exc:
        ffout = exc.output.decode(errors="ignore").strip()

        # 🔁 Fallback : tentative plus permissive
        try:
            fallback_cmd = [
                "ffprobe",
                "-v",
                "quiet",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(video_path),
            ]
            fallback_out = (
                subprocess.check_output(
                    fallback_cmd,
                    stderr=subprocess.DEVNULL,
                )
                .decode(errors="ignore")
                .strip()
            )
            return float(fallback_out)

        except Exception:
            # ❌ Là seulement, on peut parler de BADFORMAT
            raise CutMindError(
                "Fichier vidéo illisible (ffprobe).",
                code=ErrCode.BADFORMAT,
                ctx={
                    "video_path": str(video_path),
                    "ffprobe_output": ffout[:500],
                },
                original_exception=exc,
            ) from exc

    except ValueError as exc:
        raise CutMindError(
            "FFmpeg a renvoyé une durée invalide.",
            code=ErrCode.FFMPEG,
            ctx={"video_path": str(video_path), "output": output},
            original_exception=exc,
        ) from exc

    except Exception as exc:
        raise CutMindError(
            "Erreur inattendue lors de la récupération de durée.",
            code=ErrCode.UNEXPECTED,
            ctx={"video_path": str(video_path)},
            original_exception=exc,
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


def detect_nvenc_available() -> bool:
    """
    Vérifie si l'encodeur NVIDIA NVENC (hevc_nvenc) est disponible.
    """
    try:
        result = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, check=True)
        return "hevc_nvenc" in result.stdout
    except subprocess.CalledProcessError:
        return False
