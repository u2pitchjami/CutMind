from __future__ import annotations

import ffmpeg  # type: ignore

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx


class FfmpegCutExecutor:
    """
    Exécuteur technique pur : coupe une vidéo sans aucune logique
    métier ou orchestration.
    """

    def cut(
        self,
        input_path: str,
        start: float,
        end: float,
        output_path: str,
        use_cuda: bool = False,
        codec: str = "libx264",
        crf: int = 23,
        preset: str = "medium",
    ) -> None:
        try:
            hwaccel = "cuda" if use_cuda else "auto"
            (
                ffmpeg.input(input_path, ss=start, to=end, hwaccel=hwaccel)
                .output(
                    output_path,
                    vcodec=codec,
                    crf=crf,
                    preset=preset,
                    acodec="copy",  # Audio direct
                    loglevel="error",
                )
                .overwrite_output()
                .run(quiet=True)
            )
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur technique pendant le cut de la vidéo.",
                code=ErrCode.FFMPEG,
                ctx=get_step_ctx({"input_path": input_path, "start": start, "end": end, "output_path": output_path}),
            ) from exc
