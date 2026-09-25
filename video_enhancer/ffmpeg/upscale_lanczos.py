from __future__ import annotations

from pathlib import Path

from shared.ffmpegjob.ffjob import FFmpegJob, run_ffmpeg_job
from shared.utils.logger import LoggerProtocol, ensure_logger


def upscale_video_lanczos(
    video_path: Path,
    output_path: Path,
    has_audio: bool,
    target_width: int = 1920,
    target_height: int = 1080,
    logger: LoggerProtocol | None = None,
) -> None:
    """
    Upscale video using FFmpeg Lanczos scaling and encode to
    the CutMind internal standard.
    """
    logger = ensure_logger(logger, __name__)

    if target_width <= 0 or target_height <= 0:
        raise ValueError("target_width et target_height doivent être strictement positifs.")

    logger.info(
        "Starting Lanczos upscale: input=%s output=%s target=%sx%s has_audio=%s",
        video_path,
        output_path,
        target_width,
        target_height,
        has_audio,
    )

    job = FFmpegJob(
        step="upscale_video_lanczos",
        input_path=video_path,
        output_path=output_path,
        include_audio=has_audio,
        video_filters=[
            f"scale={target_width}:{target_height}:flags=lanczos",
        ],
    )

    run_ffmpeg_job(job, logger)

    logger.info(
        "Lanczos upscale completed: output=%s",
        output_path,
    )
