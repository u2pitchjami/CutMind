""" """

from __future__ import annotations

from pathlib import Path

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.config import (
    INPUT_DIR,
    OUTPUT_DIR,
    REALESRGAN_BIN,
    REALESRGAN_MODEL_DIR,
    RIFE_BIN,
    RIFE_MODEL_DIR,
    TEMP_AUDIO_DIR,
    TEMP_FRAMES_INPUT_DIR,
    TEMP_FRAMES_RIFE_DIR,
    TEMP_FRAMES_UPSCALED_DIR,
)
from shared.utils.logger import LoggerProtocol, ensure_logger
from shared.utils.settings import get_settings
from video_enhancer.executors.interpolator import interpolate_frames_with_rife
from video_enhancer.executors.upscaler import upscale_frames_with_realesrgan
from video_enhancer.ffmpeg.ffmpeg_command import convert_to_fps, interpolate_video_minterpolate
from video_enhancer.ffmpeg.frames_extract import extract_all_frames
from video_enhancer.ffmpeg.rebuilder import rebuild_video_from_frames
from video_enhancer.ffmpeg.upscale_lanczos import upscale_video_lanczos
from video_enhancer.models_cr.videojob import VideoJob


def run_enhancement_workflow(
    job: VideoJob,
    logger: LoggerProtocol | None = None,
) -> Path:
    """
    Run CutMind enhancement workflow:
    - optional Lanczos upscale
    - optional Real-ESRGAN frame upscale
    - optional RIFE interpolation
    - optional rebuild from frames
    """
    logger = ensure_logger(logger, __name__)

    settings = get_settings()
    RIFE_MODEL = settings.router_processor.rife_model
    REALESRGAN_MODEL = settings.router_processor.realesrgan_model
    UPSCALE_RATIO_DOWN = settings.router_processor.upscale_ratio_down
    method_low_fps: str = settings.router_interpolation.method_low_fps
    method_mid_fps: str = settings.router_interpolation.method_mid_fps
    method_high_fps: str = settings.router_interpolation.method_high_fps
    TARGET_FPS = settings.router_processor.target_fps

    extract_frames = False
    current_frames_dir: Path | None = None
    audio_path: Path | None = None

    try:
        if job.upscale_factor == UPSCALE_RATIO_DOWN:
            upscaled_path = INPUT_DIR / job.work_key / "upscaled.mp4"

            upscale_video_lanczos(
                video_path=job.path,
                output_path=upscaled_path,
                has_audio=job.has_audio,
                logger=logger,
            )

            job.path = upscaled_path
            logger.info("Lanczos upscale done: %s", job.path)

        elif job.upscale_factor is not None:
            frames_dir, audio_path = extract_all_frames(
                video_path=job.path,
                frames_output_dir=TEMP_FRAMES_INPUT_DIR / job.work_key,
                audio_output_path=TEMP_AUDIO_DIR / job.work_key / "audio.m4a",
                has_audio=job.has_audio,
                logger=logger,
            )

            extract_frames = True
            current_frames_dir = upscale_frames_with_realesrgan(
                input_dir=frames_dir,
                output_dir=TEMP_FRAMES_UPSCALED_DIR / job.work_key,
                upscale_factor=4,
                realesrgan_bin=REALESRGAN_BIN,
                model_dir=REALESRGAN_MODEL_DIR,
                model_name=REALESRGAN_MODEL,
                logger=logger,
            )

        if job.interpolation_method == method_low_fps:
            if current_frames_dir is None:
                frames_dir, audio_path = extract_all_frames(
                    video_path=job.path,
                    frames_output_dir=TEMP_FRAMES_INPUT_DIR / job.work_key,
                    audio_output_path=TEMP_AUDIO_DIR / job.work_key / "audio.m4a",
                    has_audio=job.has_audio,
                    logger=logger,
                )

                extract_frames = True
                current_frames_dir = frames_dir

            current_frames_dir = interpolate_frames_with_rife(
                input_dir=current_frames_dir,
                output_dir=TEMP_FRAMES_RIFE_DIR / job.work_key,
                rife_bin=RIFE_BIN,
                model_dir=RIFE_MODEL_DIR / RIFE_MODEL,
                passes=job.rife_passes,
                logger=logger,
            )
        elif job.interpolation_method in (method_mid_fps, method_high_fps):
            if extract_frames:
                if current_frames_dir is None:
                    raise CutMindError(
                        "❌ Frames manquantes après workflow enhancement.",
                        code=ErrCode.UNEXPECTED,
                        ctx=get_step_ctx({"work_key": job.work_key}),
                    )

                rebuilt_path = OUTPUT_DIR / f"{job.work_key}_rebuilt.mp4"

                job.path = rebuild_video_from_frames(
                    frames_dir=current_frames_dir,
                    output_path=rebuilt_path,
                    fps=job.fps_in,
                    audio_path=audio_path,
                    has_audio=job.has_audio,
                    logger=logger,
                )
                extract_frames = False
                current_frames_dir = None

            if job.interpolation_method == method_mid_fps:
                minterpolated_path = INPUT_DIR / job.work_key / "minterpolated.mp4"

                interpolate_video_minterpolate(
                    video_path=job.path,
                    output_path=minterpolated_path,
                    has_audio=job.has_audio,
                    target_fps=TARGET_FPS,
                    logger=logger,
                )

                job.path = minterpolated_path

            if job.interpolation_method == method_high_fps:
                converted_path = INPUT_DIR / job.work_key / "converted.mp4"
                convert_to_fps(
                    input_path=job.path,
                    output_path=converted_path,
                    fps=TARGET_FPS,
                    has_audio=job.has_audio,
                    logger=logger,
                )
                job.path = converted_path

        if extract_frames:
            if current_frames_dir is None:
                raise CutMindError(
                    "❌ Frames manquantes après workflow enhancement.",
                    code=ErrCode.UNEXPECTED,
                    ctx=get_step_ctx({"work_key": job.work_key}),
                )

            rebuilt_path = OUTPUT_DIR / f"{job.work_key}_rebuilt.mp4"

            job.path = rebuild_video_from_frames(
                frames_dir=current_frames_dir,
                output_path=rebuilt_path,
                fps=job.fps_in * (2**job.rife_passes),
                audio_path=audio_path,
                has_audio=job.has_audio,
                logger=logger,
            )

        return job.path
    except CutMindError:
        raise
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur check & fix.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx(
                {
                    "job.path.name": job.path.name,
                }
            ),
        ) from exc
