from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
import subprocess
from typing import Any

from shared.utils.settings import get_settings


class FFprobeError(RuntimeError):
    """Raised when ffprobe output is missing expected fields."""


def inspect_video(video_path: Path) -> dict[str, Any]:
    """Return first video stream metadata using ffprobe (JSON)."""
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


def is_video_compliant(metadata: dict[str, Any]) -> bool:
    """Check if video matches CutMind internal standard."""
    settings = get_settings()

    expected_codec = settings.ffsmartcut.vcodec.replace("libx265", "hevc")

    return (
        metadata.get("codec_name") == expected_codec
        and metadata.get("profile") == settings.ffsmartcut.profile
        and metadata.get("pix_fmt") == settings.ffsmartcut.pix_fmt
        and metadata.get("color_space") == settings.ffsmartcut.colorspace
        and metadata.get("color_transfer") == settings.ffsmartcut.color_trc
        and metadata.get("color_primaries") == settings.ffsmartcut.color_primaries
        and metadata.get("codec_tag_string") == settings.ffsmartcut.tag
        and metadata.get("r_frame_rate") == "60/1"
    )
