from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from check.histo.processing_checks import evaluate_segment_cut
from check.histo.processing_log import processing_step
from shared.executors.ffmpeg_cut_executor import FfmpegCutExecutor
from shared.models.db_models import Segment, Video
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.config import (
    COLOR_BLUE,
    COLOR_CYAN,
    COLOR_GREEN,
    COLOR_PURPLE,
    COLOR_RED,
    COLOR_RESET,
    COLOR_YELLOW,
)
from shared.utils.logger import LoggerProtocol, ensure_logger


@dataclass
class CutRequest:
    seg_obj: Segment
    uid: str
    start: float
    end: float
    output_path: str


@dataclass
class CutResult:
    uid: str
    output_path: str
    duration: float


class CutService:
    def __init__(self) -> None:
        self.executor = FfmpegCutExecutor()

    def cut_segments(
        self,
        vid: Video,
        input_video: str,
        segments: list[CutRequest],
        logger: LoggerProtocol | None = None,
    ) -> list[CutResult]:
        logger = ensure_logger(logger, __name__)
        logger.debug(f"Cut segments FFMPEG : {input_video} -> {len(segments)}")
        results: list[CutResult] = []
        try:
            for seg in segments:
                with processing_step(vid, seg.seg_obj, action="Cut FFMPEG") as history:
                    if seg.end <= seg.start:
                        raise CutMindError(
                            "Segment avec durée négative ou nulle.",
                            code=ErrCode.VIDEO,
                            ctx={
                                "uid": seg.uid,
                                "start": seg.start,
                                "end": seg.end,
                            },
                        )

                    try:
                        self.executor.cut(input_video, seg.start, seg.end, seg.output_path, logger=logger)
                        status, message = evaluate_segment_cut(Path(seg.output_path))
                        history.status = status
                        history.message = message
                    except CutMindError:
                        raise
                    except Exception as exc:
                        raise CutMindError(
                            "Erreur ffmpeg pendant le cut",
                            code=ErrCode.FFMPEG,
                            ctx=get_step_ctx(
                                {
                                    "uid": seg.uid,
                                    "start": seg.start,
                                    "end": seg.end,
                                    "output_path": seg.output_path,
                                }
                            ),
                        ) from exc

                duration = round(seg.end - seg.start, 3)

                results.append(
                    CutResult(
                        uid=seg.uid,
                        output_path=seg.output_path,
                        duration=duration,
                    )
                )
                self.log_cut_summary(duration, seg, vid, logger)

            return results
        except CutMindError as err:
            raise err.with_context(get_step_ctx({"input_video": input_video})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur lors de la détection de scènes : refine.",
                code=ErrCode.UNEXPECTED,
                ctx=get_step_ctx({"input_video": input_video}),
            ) from exc

    def log_cut_summary(
        self,
        duration: float,
        seg: CutRequest,
        vid: Video,
        logger: LoggerProtocol | None = None,
    ) -> None:
        """Log un résumé coloré du découpage d'un segment."""
        logger = ensure_logger(logger, __name__)

        def fmt_float(value: float | int | None) -> str:
            if value is None:
                return "N/A"
            return f"{float(value):.2f}"

        def fmt_time(value: float | int | None) -> str:
            """Formate un temps en secondes sous la forme HH:MM:SS.ss."""
            if value is None:
                return "N/A"

            total_seconds = float(value)
            hours, remainder = divmod(total_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)

            return f"{int(hours):02d}:{int(minutes):02d}:{seconds:05.2f}"

        output_path = str(seg.output_path) if seg.output_path else "N/A"
        output_color = COLOR_GREEN if seg.output_path else COLOR_RED

        logger.info(
            "%s✂️ Résumé découpe vidéo : %s%s%s",
            COLOR_PURPLE,
            COLOR_CYAN,
            vid.name,
            COLOR_RESET,
        )

        logger.info(
            "%s📌 Début      : %s%s%s",
            COLOR_BLUE,
            COLOR_YELLOW,
            fmt_time(seg.start),
            COLOR_RESET,
        )

        logger.info(
            "%s📌 Fin        : %s%s%s",
            COLOR_BLUE,
            COLOR_YELLOW,
            fmt_time(seg.end),
            COLOR_RESET,
        )

        logger.info(
            "%s📌 Durée      : %s%s s%s",
            COLOR_BLUE,
            COLOR_GREEN if duration is not None else COLOR_RED,
            fmt_float(duration),
            COLOR_RESET,
        )

        logger.info(
            "%s📌 Fichier    : %s%s%s",
            COLOR_BLUE,
            output_color,
            output_path,
            COLOR_RESET,
        )
