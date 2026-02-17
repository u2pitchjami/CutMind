from __future__ import annotations

from pathlib import Path

import ffmpeg  # type: ignore

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
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
    ) -> None:
        settings = get_settings()

        PRESET: str = settings.ffsmartcut.preset
        PIX_FMT: str = settings.ffsmartcut.pix_fmt
        VCODEC: str = settings.ffsmartcut.vcodec
        CRF: int = settings.ffsmartcut.crf
        PROFILE: str = settings.ffsmartcut.profile
        COLOR_PRIMARIES: str = settings.ffsmartcut.color_primaries
        COLOR_TRC: str = settings.ffsmartcut.color_trc
        COLORSPACE: str = settings.ffsmartcut.colorspace
        VSYNC: str = settings.ffsmartcut.vsync
        TAG: str = settings.ffsmartcut.tag
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
                    profile=PROFILE,
                    color_primaries=COLOR_PRIMARIES,
                    color_trc=COLOR_TRC,
                    colorspace=COLORSPACE,
                    vsync=VSYNC,
                    tag=TAG,
                    movflags=MOVFLAGS,
                    acodec=ACODEC,
                    audio_bitrate=AUDIO_BITRATE,
                    ar=AR,
                    ac=AC,
                    loglevel="error",
                )
                .overwrite_output()
                .run(quiet=True)
            )

        except ffmpeg.Error as exc:
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
