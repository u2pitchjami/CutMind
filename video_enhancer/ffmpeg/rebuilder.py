from __future__ import annotations

from pathlib import Path

import ffmpeg  # type: ignore

from shared.utils.logger import LoggerProtocol, ensure_logger
from shared.utils.settings import get_settings


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
    settings = get_settings()
    PRESET = settings.ffsmartcut.preset
    PIX_FMT = settings.ffsmartcut.pix_fmt
    VCODEC = settings.ffsmartcut.vcodec
    CRF = settings.ffsmartcut.crf
    PROFILE_V = settings.ffsmartcut.profile_v
    COLOR_PRIMARIES = settings.ffsmartcut.color_primaries
    COLOR_TRC = settings.ffsmartcut.color_trc
    COLORSPACE = settings.ffsmartcut.colorspace
    VSYNC = settings.ffsmartcut.vsync
    TAG_V = settings.ffsmartcut.tag_v
    MOVFLAGS = settings.ffsmartcut.movflags
    ACODEC = settings.ffsmartcut.acodec
    AUDIO_BITRATE = settings.ffsmartcut.audio_bitrate
    AR = settings.ffsmartcut.ar
    AC = settings.ffsmartcut.ac

    if not frames_dir.exists():
        raise FileNotFoundError(f"Frames directory not found: {frames_dir}")

    if not any(frames_dir.glob("frame_*.png")):
        raise VideoRebuildError(f"No frames found in: {frames_dir}")

    if has_audio and audio_path is not None and not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    frame_pattern = frames_dir / "frame_%08d.png"

    logger.info(
        "Rebuild vidéo | frames=%s | fps=%s | audio=%s | output=%s",
        frames_dir,
        fps,
        audio_path if has_audio else None,
        output_path,
    )

    try:
        video_input = ffmpeg.input(
            str(frame_pattern),
            framerate=fps,
            start_number=0,
        )

        if has_audio and audio_path is not None:
            audio_input = ffmpeg.input(str(audio_path))

            stream = ffmpeg.output(
                video_input,
                audio_input,
                str(output_path),
                vcodec=VCODEC,
                preset=PRESET,
                crf=CRF,
                pix_fmt=PIX_FMT,
                color_primaries=COLOR_PRIMARIES,
                color_trc=COLOR_TRC,
                colorspace=COLORSPACE,
                vsync=VSYNC,
                movflags=MOVFLAGS,
                acodec=ACODEC,
                audio_bitrate=AUDIO_BITRATE,
                ar=AR,
                ac=AC,
                shortest=None,
                **{"profile:v": PROFILE_V},
                **{"tag:v": TAG_V},
            )
        else:
            stream = ffmpeg.output(
                video_input,
                str(output_path),
                vcodec=VCODEC,
                preset=PRESET,
                crf=CRF,
                pix_fmt=PIX_FMT,
                color_primaries=COLOR_PRIMARIES,
                color_trc=COLOR_TRC,
                colorspace=COLORSPACE,
                vsync=VSYNC,
                movflags=MOVFLAGS,
                an=None,
                **{"profile:v": PROFILE_V},
                **{"tag:v": TAG_V},
            )

        stream.overwrite_output().run(
            capture_stdout=True,
            capture_stderr=True,
        )

    except ffmpeg.Error as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
        logger.error("FFmpeg rebuild error: %s", stderr)
        raise VideoRebuildError(f"Erreur FFmpeg lors du rebuild vidéo : {stderr}") from exc

    if not output_path.exists():
        raise VideoRebuildError(f"Output video was not created: {output_path}")

    logger.info("✅ Rebuild vidéo terminé : %s", output_path)

    return output_path
