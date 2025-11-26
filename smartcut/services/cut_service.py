from __future__ import annotations

from dataclasses import dataclass

from shared.models.exceptions import CutMindError, ErrCode
from smartcut.ffsmartcut.ffmpeg_cut_executor import FfmpegCutExecutor


@dataclass
class CutRequest:
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
        input_video: str,
        segments: list[CutRequest],
    ) -> list[CutResult]:
        results: list[CutResult] = []

        for seg in segments:
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
                self.executor.cut(input_video, seg.start, seg.end, seg.output_path)

            except Exception as exc:
                raise CutMindError(
                    "Erreur ffmpeg pendant le cut",
                    code=ErrCode.FFMPEG,
                    ctx={
                        "uid": seg.uid,
                        "start": seg.start,
                        "end": seg.end,
                        "output_path": seg.output_path,
                    },
                ) from exc

            duration = round(seg.end - seg.start, 3)

            results.append(
                CutResult(
                    uid=seg.uid,
                    output_path=seg.output_path,
                    duration=duration,
                )
            )

        return results
