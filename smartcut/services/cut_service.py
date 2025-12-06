from __future__ import annotations

from dataclasses import dataclass

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.settings import get_settings
from smartcut.executors.ffmpeg_cut_executor import FfmpegCutExecutor

settings = get_settings()

USE_CUDA = settings.smartcut.use_cuda
PRESET = settings.smartcut.preset_gpu if USE_CUDA else settings.smartcut.preset_cpu
RC = settings.ffsmartcut.rc
CQ = settings.ffsmartcut.cq
PIX_FMT = settings.ffsmartcut.pix_fmt
VCODEC = settings.smartcut.vcodec_gpu if USE_CUDA else settings.smartcut.vcodec_cpu
CRF = settings.smartcut.crf


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
        try:
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
                    self.executor.cut(input_video, seg.start, seg.end, seg.output_path, USE_CUDA, VCODEC, CRF, PRESET)

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

            return results
        except CutMindError as err:
            raise err.with_context(get_step_ctx({"input_video": input_video})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur lors de la détection de scènes : refine.",
                code=ErrCode.UNEXPECTED,
                ctx=get_step_ctx({"input_video": input_video}),
            ) from exc
