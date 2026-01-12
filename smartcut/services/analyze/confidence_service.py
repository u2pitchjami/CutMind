from __future__ import annotations

from dataclasses import dataclass

from cutmind.models_cm.db_models import Segment
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from smartcut.executors.confidence_executor import ConfidenceExecutor


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
        segments: list[Segment],
        auto_keywords: list[str],
    ) -> list[ConfidenceResult]:
        results: list[ConfidenceResult] = []

        try:
            for seg in segments:
                if not seg.id:
                    continue
                if not seg.description:
                    score = 0.0
                    merged = auto_keywords.copy()
                else:
                    score = self.executor.compute(seg.description, seg.keywords)
                    merged = list(set(seg.keywords + auto_keywords)) if seg.keywords else auto_keywords.copy()

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
