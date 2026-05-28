""" """

from __future__ import annotations

from pathlib import Path
import subprocess

import ffmpeg  # type: ignore

from shared.ffmpegjob.ffjob import FFmpegJob, run_ffmpeg_job
from shared.ffmpegjob.ffmpeg_settings import FFmpegExportSettings
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
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

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    try:
        logger.info(
            "Starting FFmpeg minterpolate: input=%s output=%s target_fps=%s has_audio=%s",
            video_path,
            output_path,
            target_fps,
            has_audio,
        )

        cfg = FFmpegExportSettings.from_settings()

        input_stream = ffmpeg.input(video_path)

        video_filtered = input_stream.video.filter(
            "minterpolate",
            fps=target_fps,
            mi_mode="mci",
            mc_mode="aobmc",
            me_mode="bidir",
            vsbmc=1,
        )

        if has_audio:
            stream = ffmpeg.output(
                video_filtered,
                input_stream.audio,
                output_path,
                **cfg.video_kwargs(),
                **cfg.audio_kwargs(),
            )

        else:
            stream = ffmpeg.output(
                video_filtered,
                output_path,
                an=None,
                **cfg.video_kwargs(),
            )

        (
            stream.overwrite_output().run(
                capture_stdout=True,
                capture_stderr=True,
            )
        )

        logger.info(
            "FFmpeg minterpolate completed: output=%s target_fps=%s",
            output_path,
            target_fps,
        )

    except subprocess.CalledProcessError as exc:
        logger.error(
            "FFmpeg minterpolate failed. returncode=%s stderr:\n%s",
            exc.returncode,
            exc.stderr,
        )
        raise CutMindError(
            "❌ Erreur FFmpeg lors de la conversion à 60 FPS.",
            code=ErrCode.FFMPEG,
            ctx=get_step_ctx(
                {
                    "step": "minterpolate",
                    "video_path": str(video_path),
                    "output_path": str(output_path),
                    "returncode": exc.returncode,
                    "stderr": exc.stderr,
                }
            ),
        ) from exc

    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors de la conversion à 60 FPS.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video_path": str(video_path)}),
        ) from exc
