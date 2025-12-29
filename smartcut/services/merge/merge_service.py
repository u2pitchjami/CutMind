from __future__ import annotations

from dataclasses import dataclass

from cutmind.models_cm.db_models import Segment
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from smartcut.executors.merge_executor import MergedSegment, MergeExecutor, RawSegment
from smartcut.services.merge.rattrapage_service import PostMergeRattrapage


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
    Service métier : prépare les données, appelle l'executor,
    applique un post-traitement (rattrapage), filtre la durée.
    """

    def __init__(
        self,
        min_duration: float,
        max_duration: float,
        threshold: float = 0.5,
        gap_confidence: float = 0.25,
        max_time_gap: float = 0.5,
        apply_rattrapage: bool = True,
    ):
        self.min_duration = min_duration
        self.max_duration = max_duration
        self.apply_rattrapage = apply_rattrapage

        self.executor = MergeExecutor(
            threshold=threshold,
            gap_confidence=gap_confidence,
            max_time_gap=max_time_gap,
        )

        self.rattrapage = PostMergeRattrapage(
            min_duration=min_duration,
            max_duration=max_duration,
            threshold=threshold,
        )

    def merge(self, segments: list[Segment]) -> list[MergeResult]:
        try:
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

            merged: list[MergedSegment] = self.executor.merge(raw_list)
            if self.apply_rattrapage:
                merged = self.rattrapage.apply(merged)

            results: list[MergeResult] = []
            for seg in merged:
                duration = seg.end - seg.start
                if duration < self.min_duration or duration > self.max_duration:
                    continue

                # ⛔️ Skip segments qui n'ont pas été fusionnés (1 seul UID)
                if len(seg.merged_from) <= 1:
                    continue

                results.append(
                    MergeResult(
                        segment_id=None,  # ➜ sera défini juste après
                        start=seg.start,
                        end=seg.end,
                        description=seg.description.strip(),
                        keywords=seg.keywords,
                        confidence=seg.confidence,
                        merged_from=seg.merged_from,
                    )
                )

            # 🔁 Réattribution d’un ID local (utile pour nommage prédictif)
            for i, result in enumerate(results, start=len(segments) + 1):
                result.segment_id = i

            return results
        except CutMindError as err:
            raise err.with_context(
                get_step_ctx({"start": seg.start, "end": seg.end, "merged_from": seg.merged_from})
            ) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur inattendue lors du merge Smartcut.",
                code=ErrCode.UNEXPECTED,
                ctx=get_step_ctx({"start": seg.start, "end": seg.end, "merged_from": seg.merged_from}),
            ) from exc
