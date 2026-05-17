from __future__ import annotations

from pathlib import Path
import subprocess

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

    frames_command = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-start_number",
        "0",
        str(frame_pattern),
    ]

    logger.info("Extraction des frames : %s", video_path.name)

    try:
        subprocess.run(
            frames_command,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        logger.error("FFmpeg frames stdout: %s", exc.stdout)
        logger.error("FFmpeg frames stderr: %s", exc.stderr)
        raise FrameExtractionError(f"Frame extraction failed for {video_path}") from exc

    if not any(frames_output_dir.glob("frame_*.png")):
        raise FrameExtractionError(f"No frames extracted from {video_path}")

    extracted_audio_path: Path | None = None

    if has_audio:
        if audio_output_path is None:
            audio_output_path = frames_output_dir.parent / "audio.m4a"

        audio_output_path.parent.mkdir(parents=True, exist_ok=True)

        audio_command = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-c:a",
            "copy",
            str(audio_output_path),
        ]

        logger.info("Extraction audio : %s", video_path.name)

        try:
            subprocess.run(
                audio_command,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            logger.error("FFmpeg audio stdout: %s", exc.stdout)
            logger.error("FFmpeg audio stderr: %s", exc.stderr)
            raise FrameExtractionError(f"Audio extraction failed for {video_path}") from exc

        extracted_audio_path = audio_output_path

    return frames_output_dir, extracted_audio_path
