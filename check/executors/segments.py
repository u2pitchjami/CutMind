from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
import subprocess
from typing import Any

from shared.utils.settings import get_settings


class FFprobeError(RuntimeError):
    """
    Raised when ffprobe output is missing expected fields.
    """


def inspect_video(video_path: Path) -> dict[str, Any]:
    """
    Return first video stream metadata using ffprobe (JSON).
    """
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,profile,pix_fmt,color_space,color_transfer,color_primaries,r_frame_rate,codec_tag_string",
        "-of",
        "json",
        str(video_path),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise FFprobeError(f"ffprobe failed: {exc.stderr}") from exc

    try:
        raw: Any = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise FFprobeError("ffprobe returned invalid JSON") from exc

    if not isinstance(raw, Mapping):
        raise FFprobeError("ffprobe JSON root is not an object")

    streams_obj: Any = raw.get("streams")
    if not isinstance(streams_obj, list) or not streams_obj:
        raise FFprobeError("ffprobe JSON has no 'streams' array")

    first_stream: Any = streams_obj[0]
    if not isinstance(first_stream, Mapping):
        raise FFprobeError("ffprobe first stream is not an object")

    # Convert Mapping[str, Any] -> dict[str, Any] for downstream mutability/typing.
    return dict(first_stream)


def _normalize_codec_name(encoder: str) -> str:
    """Convert an FFmpeg encoder name to its resulting codec name."""
    encoder_to_codec = {
        "hevc_nvenc": "hevc",
        "libx265": "hevc",
        "h264_nvenc": "h264",
        "libx264": "h264",
    }
    return encoder_to_codec.get(encoder, encoder)


def check_video_compliance(
    metadata: dict[str, Any],
) -> tuple[bool, dict[str, tuple[Any, Any]]]:
    """Check whether a video can be used without re-encoding."""
    settings = get_settings()

    expected = {
        "codec_name": _normalize_codec_name(settings.ffsmartcut.vcodec),
        "profile": settings.ffsmartcut.profile.lower(),
        "pix_fmt": settings.ffsmartcut.pix_fmt,
        "color_space": settings.ffsmartcut.colorspace,
        "codec_tag_string": settings.ffsmartcut.tag,
        "r_frame_rate": "60/1",
    }

    normalized_metadata = dict(metadata)

    profile = normalized_metadata.get("profile")
    if isinstance(profile, str):
        normalized_metadata["profile"] = profile.lower()

    mismatches = {
        key: (normalized_metadata.get(key), expected_value)
        for key, expected_value in expected.items()
        if normalized_metadata.get(key) != expected_value
    }

    return not mismatches, mismatches
