from __future__ import annotations

from pathlib import Path

from shared.ffmpegjob.ffjob import FFmpegJob, run_ffmpeg_job
from shared.utils.logger import LoggerProtocol, ensure_logger


class FrameExtractionError(RuntimeError):
    """Raised when frame extraction fails."""


def extract_all_frames(
    video_path: Path,
    frames_output_dir: Path,
    audio_output_path: Path | None = None,
    has_audio: bool = False,
    logger: LoggerProtocol | None = None,
) -> tuple[Path, Path | None]:
    """Extract all video frames and optionally audio from a video segment."""

    logger = ensure_logger(logger, __name__)

    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    frames_output_dir.mkdir(parents=True, exist_ok=True)

    frame_pattern = frames_output_dir / "frame_%08d.png"

    run_ffmpeg_job(
        FFmpegJob(
            step="extract_frames",
            input_path=video_path,
            output_path=frame_pattern,
            include_audio=False,
            output_args=[
                "-start_number",
                "0",
            ],
            use_common_video_args=False,
        ),
        logger=logger,
    )

    logger.info("Extraction des frames : %s", video_path.name)

    if not any(frames_output_dir.glob("frame_*.png")):
        raise FrameExtractionError(f"No frames extracted from {video_path}")

    extracted_audio_path: Path | None = None

    if has_audio:
        if audio_output_path is None:
            audio_output_path = frames_output_dir.parent / "audio.m4a"

        audio_output_path.parent.mkdir(parents=True, exist_ok=True)

        run_ffmpeg_job(
            FFmpegJob(
                step="extract_audio",
                input_path=video_path,
                output_path=audio_output_path,
                include_audio=True,
                audio_args=[
                    "-c:a",
                    "copy",
                ],
                output_args=[
                    "-vn",
                ],
                use_common_video_args=False,
            ),
            logger=logger,
        )

        logger.info("Extraction audio : %s", video_path.name)

        extracted_audio_path = audio_output_path

    return frames_output_dir, extracted_audio_path
