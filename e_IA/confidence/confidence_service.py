from __future__ import annotations

from dataclasses import dataclass

from e_IA.confidence.confidence_executor import ConfidenceExecutor
from g_check.histo.processing_checks import evaluate_confidence_output
from g_check.histo.processing_log import processing_step
from shared.models.db_models import Segment, Video
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx


@dataclass
class ConfidenceResult:
    segment_id: int
    confidence: float
    merged_keywords: list[str]


class ConfidenceService:
    """
    Service qui applique le calcul de confiance aux segments IA done.

    Ne touche pas à la session, ne fait pas de logs métier importants.
    """

    def __init__(self, model_name: str):
        self.model_name = model_name
        self.executor = ConfidenceExecutor(model_name)

    def compute_for_segments(
        self,
        vid: Video,
        segments: list[Segment],
        auto_keywords: list[str],
    ) -> list[ConfidenceResult]:
        results: list[ConfidenceResult] = []

        try:
            for seg in segments:
                with processing_step(vid, seg, action="Confidence IA") as history:
                    if not seg.id:
                        continue
                    if not seg.description:
                        score = 0.0
                        merged = auto_keywords.copy()
                    else:
                        score = self.executor.compute(seg.description, seg.keywords)
                        merged = list(set(seg.keywords + auto_keywords)) if seg.keywords else auto_keywords.copy()

                    status, message = evaluate_confidence_output(score)
                    history.status = status
                    history.message = message
                    results.append(
                        ConfidenceResult(
                            segment_id=seg.id,
                            confidence=score,
                            merged_keywords=merged,
                        )
                    )

            return results
        except CutMindError as err:
            raise err.with_context(get_step_ctx({"seg.id": seg.id})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur inattendue lors de du traitement compute_for_segments.",
                code=ErrCode.UNEXPECTED,
                ctx=get_step_ctx({"seg.id": seg.id}),
            ) from exc
