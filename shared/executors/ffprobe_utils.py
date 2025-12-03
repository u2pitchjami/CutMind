from __future__ import annotations

import json
from pathlib import Path
import subprocess

from shared.models.exceptions import CutMindError, ErrCode
from shared.models.ffprobe import FFprobeData, FFprobeStream

# ============================================================
# 🔧 Fonction interne : exécute ffprobe et renvoie du JSON
# ============================================================


def _ffprobe_json(video_path: Path) -> FFprobeData:
    """
    Exécute ffprobe en JSON. Ne doit jamais être appelé direct
    en dehors de ce module (helper interne).

    Renvoie un dict, ou lève CutMindError en cas d'erreur.
    """
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(video_path),
    ]

    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        data: FFprobeData = json.loads(out.decode("utf-8"))
        return data
    except subprocess.CalledProcessError as exc:
        raise CutMindError(
            "FFprobe a échoué.",
            code=ErrCode.FFMPEG,
            ctx={"video_path": str(video_path), "output": exc.output.decode("utf-8")},
        ) from exc
    except Exception as exc:
        raise CutMindError(
            "Erreur interne FFprobe.", code=ErrCode.UNEXPECTED, ctx={"video_path": str(video_path)}
        ) from exc


# ============================================================
# 🔧 Extraction du flux vidéo principal
# ============================================================


def _get_video_stream(probe: FFprobeData, video_path: Path) -> FFprobeStream:
    """
    Retourne le premier flux vidéo du ffprobe.
    Lève CutMindError si aucun flux trouvé.
    """
    for stream in probe["streams"]:
        if stream.get("codec_type") == "video":
            return stream

    raise CutMindError("Aucun flux vidéo trouvé.", code=ErrCode.FILE_ERROR, ctx={"video_path": str(video_path)})


# ============================================================
# 🔧 Métadonnées individuelles
# ============================================================


def get_duration(video_path: Path) -> float:
    """
    Retourne la durée en secondes.
    Lève CutMindError en cas d'échec.
    """
    probe = _ffprobe_json(video_path)
    fmt = probe.get("format", {})

    try:
        return float(fmt.get("duration", 0.0))
    except Exception as exc:  # pylint: disable=broad-except
        raise CutMindError(
            "Durée illisible dans FFprobe.", code=ErrCode.FILE_ERROR, ctx={"video_path": str(video_path)}
        ) from exc


def get_fps(video_path: Path) -> float:
    """
    Retourne le FPS réel, via avg_frame_rate.
    """
    probe = _ffprobe_json(video_path)
    stream = _get_video_stream(probe, video_path)

    avg_rate = stream.get("avg_frame_rate", "0/0")
    try:
        num, den = avg_rate.split("/")
        num_f = float(num)
        den_f = float(den)
        return num_f / den_f if den_f > 0 else 0.0
    except Exception as exc:  # pylint: disable=broad-except
        raise CutMindError(
            "FPS illisible dans FFprobe.",
            code=ErrCode.FILE_ERROR,
            ctx={"video_path": str(video_path), "avg_frame_rate": avg_rate},
        ) from exc


def get_resolution(video_path: Path) -> str:
    """
    Retourne la résolution formatée : "1920x1080".
    """
    probe = _ffprobe_json(video_path)
    stream = _get_video_stream(probe, video_path)

    width = stream.get("width")
    height = stream.get("height")

    if not width or not height:
        raise CutMindError(
            "Impossible de lire la résolution.", code=ErrCode.FILE_ERROR, ctx={"video_path": str(video_path)}
        )

    return f"{width}x{height}"


def get_codec(video_path: Path) -> str | None:
    """
    Retourne le codec vidéo.
    """
    probe = _ffprobe_json(video_path)
    stream = _get_video_stream(probe, video_path)
    return stream.get("codec_name")


def get_bitrate(video_path: Path) -> int | None:
    """
    Retourne le bitrate global (bps).
    Parfois absent dans ffprobe → renvoie None.
    """
    probe = _ffprobe_json(video_path)
    fmt = probe.get("format", {})

    br = fmt.get("bit_rate")
    try:
        return int(br) if br else None
    except (TypeError, ValueError):
        return None
