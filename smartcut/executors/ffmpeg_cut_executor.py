from __future__ import annotations

from pathlib import Path

import ffmpeg  # type: ignore

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.logger import LoggerProtocol, ensure_logger
from shared.utils.settings import get_settings


class FfmpegCutExecutor:
    """
    Exécuteur technique pur : coupe une vidéo avec paramètres
    centralisés dans les settings.
    """

    def cut(
        self,
        input_path: str,
        start: float,
        end: float,
        output_path: str,
        logger: LoggerProtocol | None = None,
    ) -> None:
        logger = ensure_logger(logger, __name__)
        settings = get_settings()

        PRESET: str = settings.ffsmartcut.preset
        PIX_FMT: str = settings.ffsmartcut.pix_fmt
        VCODEC: str = settings.ffsmartcut.vcodec
        CRF: int = settings.ffsmartcut.crf
        PROFILE_V: str = settings.ffsmartcut.profile_v
        COLOR_PRIMARIES: str = settings.ffsmartcut.color_primaries
        COLOR_TRC: str = settings.ffsmartcut.color_trc
        COLORSPACE: str = settings.ffsmartcut.colorspace
        VSYNC: str = settings.ffsmartcut.vsync
        TAG_V: str = settings.ffsmartcut.tag_v
        MOVFLAGS: str = settings.ffsmartcut.movflags
        ACODEC: str = settings.ffsmartcut.acodec
        AUDIO_BITRATE: str = settings.ffsmartcut.audio_bitrate
        AR: int = settings.ffsmartcut.ar
        AC: int = settings.ffsmartcut.ac

        input_file = Path(input_path)
        output_file = Path(output_path)

        if not input_file.exists():
            raise FileNotFoundError(f"Input video not found: {input_path}")

        try:
            (
                ffmpeg.input(str(input_file))
                .output(
                    str(output_file),
                    ss=start,  # seek précis (après -i)
                    to=end,
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
                    loglevel="error",
                    **{"profile:v": PROFILE_V},
                    **{"tag:v": TAG_V},
                )
                .overwrite_output()
                .run(quiet=True)
            )

        except ffmpeg.Error as exc:
            stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
            logger.error("FFmpeg failed. stderr:\n%s", stderr)
            raise CutMindError(
                "❌ Erreur technique pendant le cut de la vidéo.",
                code=ErrCode.FFMPEG,
                ctx=get_step_ctx(
                    {
                        "input_path": input_path,
                        "start": start,
                        "end": end,
                        "output_path": output_path,
                    }
                ),
                original_exception=exc,
            ) from exc

        if not output_file.exists():
            raise CutMindError(
                "❌ Le segment n'a pas été généré.",
                code=ErrCode.FFMPEG,
                ctx=get_step_ctx({"output_path": output_path}),
            )
