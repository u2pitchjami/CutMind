from __future__ import annotations

import ffmpeg  # type: ignore

from shared.models.exceptions import CutMindError, ErrCode
from shared.utils.logger import LoggerProtocol, ensure_logger
from shared.utils.settings import get_settings


def upscale_video_lanczos(
    video_path: str,
    output_path: str,
    has_audio: bool,
    target_width: int = 1920,
    target_height: int = 1080,
    logger: LoggerProtocol | None = None,
) -> None:
    """
    Upscale video using FFmpeg Lanczos scaling and encode to CutMind internal standard.
    """
    logger = ensure_logger(logger, __name__)
    settings = get_settings()

    try:
        logger.info(
            "Starting Lanczos upscale: input=%s output=%s target=%sx%s has_audio=%s",
            video_path,
            output_path,
            target_width,
            target_height,
            has_audio,
        )

        input_stream = ffmpeg.input(video_path)

        video_scaled = input_stream.video.filter(
            "scale",
            target_width,
            target_height,
            flags="lanczos",
        )

        output_kwargs = {
            "vcodec": settings.ffsmartcut.vcodec,
            "preset": settings.ffsmartcut.preset,
            "crf": settings.ffsmartcut.crf,
            "pix_fmt": settings.ffsmartcut.pix_fmt,
            "color_primaries": settings.ffsmartcut.color_primaries,
            "color_trc": settings.ffsmartcut.color_trc,
            "colorspace": settings.ffsmartcut.colorspace,
            "vsync": settings.ffsmartcut.vsync,
            "movflags": settings.ffsmartcut.movflags,
            "profile:v": settings.ffsmartcut.profile_v,
            "tag:v": settings.ffsmartcut.tag_v,
        }

        if has_audio:
            stream = ffmpeg.output(
                video_scaled,
                input_stream.audio,
                output_path,
                acodec=settings.ffsmartcut.acodec,
                audio_bitrate=settings.ffsmartcut.audio_bitrate,
                ar=settings.ffsmartcut.ar,
                ac=settings.ffsmartcut.ac,
                **output_kwargs,
            )
        else:
            stream = ffmpeg.output(
                video_scaled,
                output_path,
                an=None,
                **output_kwargs,
            )

        (
            stream.overwrite_output().run(
                capture_stdout=True,
                capture_stderr=True,
            )
        )

        logger.info("Lanczos upscale completed: output=%s", output_path)

    except ffmpeg.Error as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
        logger.error("FFmpeg Lanczos upscale failed. stderr:\n%s", stderr)

        raise CutMindError(
            "[FFMPEG] ❌ Erreur pendant l'upscale Lanczos",
            code=ErrCode.FFMPEG,
            ctx={
                "step": "upscale_video_lanczos",
                "video_path": video_path,
                "output_path": output_path,
                "has_audio": has_audio,
                "target_width": target_width,
                "target_height": target_height,
                "stderr": stderr,
            },
        ) from exc
