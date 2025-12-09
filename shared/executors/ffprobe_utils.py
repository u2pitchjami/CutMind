from __future__ import annotations

import json
from pathlib import Path
import subprocess

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.models.ffprobe import FFprobeData, FFprobeStream
from shared.services.video_preparation import VideoPrepared

# ============================================================
# 🧰 Helper interne
# ============================================================


def _get_probe_or_load(probe: FFprobeData | None, video_path: Path) -> FFprobeData:
    """Retourne `probe` si fourni, sinon charge via ffprobe."""
    return probe if probe is not None else _ffprobe_json(video_path)


# ============================================================
# 🔧 Exécution FFprobe → JSON
# ============================================================


def _ffprobe_json(video_path: Path) -> FFprobeData:
    """
    Exécute ffprobe (JSON complet) et renvoie le dictionnaire typé.
    Ne doit pas être utilisé hors module : utilises `_get_probe_or_load()`.
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
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        data: FFprobeData = json.loads(output.decode("utf-8"))
        return data

    except subprocess.CalledProcessError as exc:
        raise CutMindError(
            "❌ FFprobe a échoué.",
            code=ErrCode.FFMPEG,
            ctx=get_step_ctx(
                {
                    "video_path": str(video_path),
                    "error": exc.output.decode("utf-8"),
                }
            ),
        ) from exc

    except Exception as exc:  # pylint: disable=broad-except
        raise CutMindError(
            "❌ Erreur interne FFprobe.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video_path": str(video_path)}),
        ) from exc


# ============================================================
# 🔍 Extraction des streams
# ============================================================


def _get_video_stream(probe: FFprobeData, video_path: Path) -> FFprobeStream:
    """Retourne le premier flux vidéo ou lève CutMindError."""
    for stream in probe.get("streams", []):
        if stream.get("codec_type") == "video":
            return stream

    raise CutMindError(
        "❌ Aucun flux vidéo trouvé.",
        code=ErrCode.FILE_ERROR,
        ctx=get_step_ctx({"video_path": str(video_path)}),
    )


def _get_audio_stream(probe: FFprobeData) -> FFprobeStream | None:
    """Retourne le premier flux audio, ou None."""
    for stream in probe.get("streams", []):
        if stream.get("codec_type") == "audio":
            return stream
    return None


# ============================================================
# 🎞️ Métadonnées vidéo
# ============================================================


def get_duration(video_path: Path, probe: FFprobeData | None = None) -> float:
    probe = _get_probe_or_load(probe, video_path)
    fmt = probe.get("format", {})
    raw = fmt.get("duration")

    try:
        return float(raw) if raw is not None else 0.0
    except Exception as exc:
        raise CutMindError(
            "❌ Durée illisible.",
            code=ErrCode.FILE_ERROR,
            ctx=get_step_ctx({"video_path": str(video_path)}),
        ) from exc


def get_fps(video_path: Path, probe: FFprobeData | None = None) -> float:
    probe = _get_probe_or_load(probe, video_path)
    stream = _get_video_stream(probe, video_path)

    rate = stream.get("avg_frame_rate", "0/1")
    try:
        num_str, den_str = rate.split("/")
        num = float(num_str)
        den = float(den_str)
        return num / den if den else 0.0
    except Exception as exc:
        raise CutMindError(
            "❌ FPS illisible.",
            code=ErrCode.FILE_ERROR,
            ctx=get_step_ctx({"video_path": str(video_path), "avg_frame_rate": rate}),
        ) from exc


def get_resolution(video_path: Path, probe: FFprobeData | None = None) -> str:
    probe = _get_probe_or_load(probe, video_path)
    stream = _get_video_stream(probe, video_path)

    width = stream.get("width")
    height = stream.get("height")

    if isinstance(width, int) and isinstance(height, int):
        return f"{width}x{height}"

    raise CutMindError(
        "❌ Résolution illisible.",
        code=ErrCode.FILE_ERROR,
        ctx=get_step_ctx({"video_path": str(video_path)}),
    )


def get_codec(video_path: Path, probe: FFprobeData | None = None) -> str | None:
    probe = _get_probe_or_load(probe, video_path)
    stream = _get_video_stream(probe, video_path)
    return stream.get("codec_name")


def get_bitrate(video_path: Path, probe: FFprobeData | None = None) -> int | None:
    probe = _get_probe_or_load(probe, video_path)
    fmt = probe.get("format", {})

    raw = fmt.get("bit_rate")
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    if isinstance(raw, (int | float)):
        return int(raw)
    return None


def get_total_frames(video_path: Path, probe: FFprobeData | None = None) -> int:
    probe = _get_probe_or_load(probe, video_path)
    stream = _get_video_stream(probe, video_path)

    raw = stream.get("nb_frames")

    if isinstance(raw, str) and raw.isdigit():
        return int(raw)

    # fallback estimation
    fps = get_fps(video_path, probe)
    raw_dur = stream.get("duration")

    if isinstance(raw_dur, (int | float)):
        duration = float(raw_dur)
    elif isinstance(raw_dur, str):
        try:
            duration = float(raw_dur)
        except ValueError:
            duration = 0.0
    else:
        duration = 0.0

    return int(duration * fps)


# ============================================================
# 🔊 Métadonnées audio
# ============================================================


def has_audio(video_path: Path, probe: FFprobeData | None = None) -> bool:
    probe = _get_probe_or_load(probe, video_path)
    return _get_audio_stream(probe) is not None


def get_audio_codec(video_path: Path, probe: FFprobeData | None = None) -> str | None:
    probe = _get_probe_or_load(probe, video_path)
    stream = _get_audio_stream(probe)
    return stream.get("codec_name") if stream else None


def get_sample_rate(video_path: Path, probe: FFprobeData | None = None) -> int | None:
    probe = _get_probe_or_load(probe, video_path)
    stream = _get_audio_stream(probe)
    if not stream:
        return None

    raw = stream.get("sample_rate")

    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    if isinstance(raw, (int | float)):
        return int(raw)
    return None


def get_channels(video_path: Path, probe: FFprobeData | None = None) -> int | None:
    probe = _get_probe_or_load(probe, video_path)
    stream = _get_audio_stream(probe)
    if not stream:
        return None

    raw = stream.get("channels")

    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    return None


def get_audio_duration(video_path: Path, probe: FFprobeData | None = None) -> float | None:
    probe = _get_probe_or_load(probe, video_path)
    stream = _get_audio_stream(probe)
    if not stream:
        return None

    raw = stream.get("duration")

    if isinstance(raw, (int | float)):
        return float(raw)
    if isinstance(raw, str):
        try:
            return float(raw)
        except ValueError:
            return None

    return None


# ============================================================
# 🚀 Fonction orchestratrice : toutes métadonnées en 1 ffprobe
# ============================================================


def get_metadata_all(video_path: Path) -> VideoPrepared:
    """Analyse complète des métadonnées vidéo + audio."""
    probe = _ffprobe_json(video_path)

    return VideoPrepared(
        path=video_path,
        duration=get_duration(video_path, probe),
        fps=get_fps(video_path, probe),
        resolution=get_resolution(video_path, probe),
        codec=get_codec(video_path, probe),
        bitrate=get_bitrate(video_path, probe),
        nb_frames=get_total_frames(video_path, probe),
        filesize_mb=round(video_path.stat().st_size / (1024 * 1024), 2),
        has_audio=has_audio(video_path, probe),
        audio_codec=get_audio_codec(video_path, probe),
        sample_rate=get_sample_rate(video_path, probe),
        channels=get_channels(video_path, probe),
        audio_duration=get_audio_duration(video_path, probe),
    )
