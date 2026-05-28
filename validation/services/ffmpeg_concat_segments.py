from __future__ import annotations

from pathlib import Path
import tempfile

from shared.ffmpegjob.ffjob import FFmpegJob, run_ffmpeg_job
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.logger import LoggerProtocol, ensure_logger


def ffmpeg_concat_segments(
    *,
    input_files: list[str],
    output_file: str,
    has_audio: bool,
    logger: LoggerProtocol,
) -> None:
    """
    Concatène plusieurs fichiers vidéo via ffmpeg concat demuxer.

    Ré-encode avec le profil interne CutMind.
    """

    logger = ensure_logger(logger, __name__)

    if len(input_files) < 2:
        raise CutMindError(
            "Concat ffmpeg invalide : au moins deux fichiers requis.",
            code=ErrCode.BADFORMAT,
            ctx=get_step_ctx({"input_files": input_files}),
        )

    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    list_file: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".txt",
            delete=False,
            encoding="utf-8",
        ) as file:
            list_file = Path(file.name)

            for file_path in input_files:
                path = Path(file_path)

                if not path.exists():
                    raise CutMindError(
                        "Fichier d'entrée introuvable pour concat.",
                        code=ErrCode.UNEXPECTED,
                        ctx=get_step_ctx({"path": str(path)}),
                    )

                escaped_path = path.as_posix().replace("'", r"'\''")
                file.write(f"file '{escaped_path}'\n")

        run_ffmpeg_job(
            FFmpegJob(
                step="ffmpeg_concat_segments",
                input_path=list_file,
                output_path=output_path,
                include_audio=has_audio,
                input_args=[
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                ],
            ),
            logger=logger,
        )

        logger.info(
            "🎬 ffmpeg concat OK → %s (%d fichiers)",
            output_path.name,
            len(input_files),
        )

    finally:
        if list_file is not None:
            try:
                list_file.unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "Impossible de supprimer le fichier temporaire %s",
                    list_file,
                )
