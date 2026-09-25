from __future__ import annotations

from pathlib import Path

from shared.ffmpegjob.ffjob import FFmpegJob, run_ffmpeg_job
from shared.utils.logger import LoggerProtocol, ensure_logger


class FfmpegCutExecutor:
    """
    Exécuteur technique pur pour la découpe vidéo via FFmpegJob.
    """

    def cut(
        self,
        input_path: str,
        start: float,
        end: float,
        output_path: str,
        logger: LoggerProtocol | None = None,
    ) -> None:
        """
        Cut a video segment and encode it using the CutMind internal standard.
        """
        logger = ensure_logger(logger, __name__)

        input_file = Path(input_path)
        output_file = Path(output_path)

        logger.debug(
            "Cut FFmpeg: input=%s start=%s end=%s output=%s",
            input_file,
            start,
            end,
            output_file,
        )

        if not input_file.exists():
            logger.error(
                "Input video not found: %s",
                input_file,
            )
            raise FileNotFoundError(f"Input video not found: {input_file}")

        duration = end - start

        if duration <= 0:
            raise ValueError(f"Invalid cut interval: start={start}, end={end}")

        job = FFmpegJob(
            step="ffmpeg_cut",
            input_path=input_file,
            output_path=output_file,
            output_args=[
                "-ss",
                f"{start:.6f}",
                "-t",
                f"{duration:.6f}",
            ],
        )

        run_ffmpeg_job(job, logger)

        logger.debug(
            "Cut FFmpeg succeeded: %s",
            output_file,
        )
