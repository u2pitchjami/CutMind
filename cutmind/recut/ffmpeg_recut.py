from __future__ import annotations

from pathlib import Path
import subprocess

from shared.utils.logger import LoggerProtocol, ensure_logger


def ffmpeg_cut_one_segment(
    input_path: Path,
    start: float,
    end: float,
    output_path: Path,
    logger: LoggerProtocol | None = None,
) -> Path:
    """
    Extrait un SEUL segment entre start et end.
    """

    logger = ensure_logger(logger, __name__)

    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(start),
        "-to",
        str(end),
        "-i",
        str(input_path),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(output_path),
    ]

    subprocess.run(cmd, check=True)
    return output_path
