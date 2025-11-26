from __future__ import annotations

from dataclasses import dataclass

from cutmind.models_cm.db_models import Segment
from smartcut.merge.merge_executor import MergeExecutor, RawSegment


@dataclass
class MergeResult:
    segment_id: int | None
    start: float
    end: float
    description: str
    keywords: list[str]
    confidence: float
    merged_from: list[str]


class MergeService:
    """
    Service métier : prépare les données RawSegment, appelle l'executor,
    applique les règles min/max duration.
    """

    def __init__(self, min_duration: float, max_duration: float):
        self.min_duration = min_duration
        self.max_duration = max_duration
        self.executor = MergeExecutor()

    def merge(self, segments: list[Segment]) -> list[MergeResult]:
        raw_list: list[RawSegment] = [
            RawSegment(
                start=s.start,
                end=s.end,
                description=s.description or "",
                keywords=list(s.keywords),
                confidence=s.confidence or 0.0,
                uid=s.uid,
            )
            for s in segments
        ]

        merged = self.executor.merge(raw_list)

        results: list[MergeResult] = []
        for i, seg in enumerate(merged, start=1):
            if (seg.end - seg.start) < self.min_duration:
                continue
            if (seg.end - seg.start) > self.max_duration:
                continue

            results.append(
                MergeResult(
                    segment_id=None,
                    start=seg.start,
                    end=seg.end,
                    description=seg.description,
                    keywords=seg.keywords,
                    confidence=seg.confidence,
                    merged_from=seg.merged_from,
                )
            )

        return results
