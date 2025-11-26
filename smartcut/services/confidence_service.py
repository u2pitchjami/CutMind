from __future__ import annotations

from dataclasses import dataclass

from cutmind.models_cm.db_models import Segment
from shared.executors.confidence_executor import ConfidenceExecutor


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
        self.executor = ConfidenceExecutor(model_name)

    def compute_for_segments(
        self,
        segments: list[Segment],
        auto_keywords: list[str],
    ) -> list[ConfidenceResult]:
        results: list[ConfidenceResult] = []

        for seg in segments:
            if seg.status != "ia_done":
                continue

            if not seg.description or not seg.id:
                score = 0.0
                continue
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
