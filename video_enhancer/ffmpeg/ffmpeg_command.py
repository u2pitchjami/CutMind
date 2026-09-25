""" """

from __future__ import annotations

from pathlib import Path

from shared.ffmpegjob.ffjob import FFmpegJob, run_ffmpeg_job
from shared.utils.logger import LoggerProtocol, ensure_logger


def convert_to_fps(
    input_path: Path,
    output_path: Path,
    fps: int,
    has_audio: bool,
    logger: LoggerProtocol | None = None,
) -> Path:
    """
    Force une vidéo à 60 FPS en respectant le profil interne CutMind.
    """
    return run_ffmpeg_job(
        FFmpegJob(
            step="convert_to_fps",
            input_path=input_path,
            output_path=output_path,
            video_filters=[f"fps={fps}"],
            include_audio=has_audio,
        ),
        logger=logger,
    )


def interpolate_video_minterpolate(
    video_path: Path,
    output_path: Path,
    has_audio: bool,
    target_fps: int = 60,
    logger: LoggerProtocol | None = None,
) -> None:
    """
    Interpolate video directly with FFmpeg minterpolate filter.

    Used for moderate FPS increase without extracting frames.
    Example: 45/50 fps -> 60 fps.
    """
    logger = ensure_logger(logger, __name__)

    if target_fps <= 0:
        raise ValueError(f"target_fps must be greater than zero: {target_fps}")

    logger.info(
        "Starting FFmpeg minterpolate: input=%s output=%s target_fps=%s has_audio=%s",
        video_path,
        output_path,
        target_fps,
        has_audio,
    )

    job = FFmpegJob(
        step="minterpolate",
        input_path=video_path,
        output_path=output_path,
        include_audio=has_audio,
        video_filters=[(f"minterpolate=fps={target_fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1")],
    )

    run_ffmpeg_job(job, logger)

    logger.info(
        "FFmpeg minterpolate completed: output=%s target_fps=%s",
        output_path,
        target_fps,
    )
