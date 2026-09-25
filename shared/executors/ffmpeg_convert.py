"""
Commandes FFmpeg pour SmartCut.
"""

from __future__ import annotations

from pathlib import Path

from shared.ffmpegjob.ffjob import FFmpegJob, run_ffmpeg_job
from shared.utils.logger import LoggerProtocol, ensure_logger


def convert_safe_video_format(
    video_path: str,
    output_path: str,
    logger: LoggerProtocol | None = None,
) -> None:
    """
    Normalize video to CutMind internal standard
    (HEVC / yuv420p / bt709 / CFR).
    """
    logger = ensure_logger(logger, __name__)

    input_path = Path(video_path)
    normalized_output_path = Path(output_path)

    logger.info(
        "Starting video normalization: input=%s output=%s",
        input_path,
        normalized_output_path,
    )

    job = FFmpegJob(
        step="convert_safe_video_format",
        input_path=input_path,
        output_path=normalized_output_path,
        include_audio=True,
    )

    run_ffmpeg_job(job, logger)

    logger.info(
        "Video normalization completed: output=%s",
        normalized_output_path,
    )
