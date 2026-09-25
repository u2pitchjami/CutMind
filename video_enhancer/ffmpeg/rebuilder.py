from __future__ import annotations

from pathlib import Path

from shared.ffmpegjob.ffjob import FFmpegInput, FFmpegJob, run_ffmpeg_job
from shared.utils.logger import LoggerProtocol, ensure_logger


class VideoRebuildError(RuntimeError):
    """Raised when video rebuild fails."""


def rebuild_video_from_frames(
    frames_dir: Path,
    output_path: Path,
    fps: float,
    audio_path: Path | None = None,
    has_audio: bool = False,
    logger: LoggerProtocol | None = None,
) -> Path:
    """Rebuild a video from extracted frames, with optional audio."""
    logger = ensure_logger(logger, __name__)

    if not frames_dir.exists():
        raise FileNotFoundError(f"Frames directory not found: {frames_dir}")

    if not any(frames_dir.glob("*.png")):
        raise VideoRebuildError(f"No frames found in: {frames_dir}")

    if fps <= 0:
        raise ValueError(f"FPS must be greater than zero: {fps}")

    if has_audio and audio_path is None:
        raise VideoRebuildError("has_audio=True but no audio_path was provided.")

    if has_audio and audio_path is not None and not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    frame_pattern, start_number = detect_frame_pattern(frames_dir)

    logger.info(
        "Rebuild vidéo | frames=%s | fps=%s | audio=%s | output=%s",
        frames_dir,
        fps,
        audio_path if has_audio else None,
        output_path,
    )

    additional_inputs: list[FFmpegInput] = []

    if has_audio and audio_path is not None:
        additional_inputs.append(FFmpegInput(path=audio_path))

    job = FFmpegJob(
        step="rebuild_video_from_frames",
        input_path=frame_pattern,
        input_args=[
            "-framerate",
            str(fps),
            "-start_number",
            str(start_number),
        ],
        additional_inputs=additional_inputs,
        output_path=output_path,
        include_audio=has_audio,
        output_args=["-shortest"] if has_audio else [],
    )

    run_ffmpeg_job(job, logger)

    if not output_path.exists():
        raise VideoRebuildError(f"Output video was not created: {output_path}")

    logger.info(
        "✅ Rebuild vidéo terminé : %s",
        output_path,
    )

    return output_path


def detect_frame_pattern(frames_dir: Path) -> tuple[Path, int]:
    png_files = sorted(frames_dir.glob("*.png"))

    if not png_files:
        raise VideoRebuildError(f"No PNG frames found in: {frames_dir}")

    first_name = png_files[0].name

    if first_name.startswith("frame_"):
        number_part = first_name.removeprefix("frame_").removesuffix(".png")
        return frames_dir / f"frame_%0{len(number_part)}d.png", int(number_part)

    number_part = first_name.removesuffix(".png")
    return frames_dir / f"%0{len(number_part)}d.png", int(number_part)
