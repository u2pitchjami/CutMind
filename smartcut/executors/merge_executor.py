from __future__ import annotations

from dataclasses import dataclass
import re

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx


@dataclass
class RawSegment:
    start: float
    end: float
    description: str
    keywords: list[str]
    confidence: float
    uid: str


@dataclass
class MergedSegment:
    start: float
    end: float
    description: str
    keywords: list[str]
    confidence: float
    merged_from: list[str]


def clean(text: str) -> list[str]:
    return re.sub(r"[^\w\s]", " ", text.lower()).split()


def keyword_similarity(a: list[str], b: list[str]) -> float:
    words_a = [w for kw in a for w in clean(kw)]
    words_b = [w for kw in b for w in clean(kw)]
    set_a = set(words_a)
    set_b = set(words_b)
    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    return inter / union if union > 0 else 0.0


class MergeExecutor:
    """
    Exécuteur pur : fusionne les segments adjacents selon des règles :
    - distance temporelle
    - similarité sémantique
    - différence de confiance
    """

    def __init__(self, threshold: float = 0.5, gap_confidence: float = 0.25, max_time_gap: float = 0.5):
        self.threshold = threshold
        self.gap_confidence = gap_confidence
        self.max_time_gap = max_time_gap
        print(f"MergeExecutor(threshold={threshold}, gap_confidence={gap_confidence}, max_time_gap={max_time_gap})")

    def merge(self, segments: list[RawSegment]) -> list[MergedSegment]:
        if not segments:
            return []

        segments = sorted(segments, key=lambda s: s.start)
        merged: list[MergedSegment] = []

        current = segments[0]
        merged_from = [current.uid]

        try:
            for seg in segments[1:]:
                time_gap = abs(seg.start - current.end)
                sim = keyword_similarity(current.keywords, seg.keywords)
                conf_gap = abs(current.confidence - seg.confidence)

                if time_gap <= self.max_time_gap and sim >= self.threshold and conf_gap <= self.gap_confidence:
                    # Fusion
                    current = RawSegment(
                        start=current.start,
                        end=seg.end,
                        description=f"{current.description} {seg.description}".strip(),
                        keywords=list(set(current.keywords + seg.keywords)),
                        confidence=max(current.confidence, seg.confidence),
                        uid=current.uid,
                    )
                    merged_from.append(seg.uid)
                else:
                    # Ajout du segment précédent (fusionné ou non)
                    merged.append(
                        MergedSegment(
                            start=current.start,
                            end=current.end,
                            description=current.description.strip(),
                            keywords=current.keywords,
                            confidence=current.confidence,
                            merged_from=merged_from.copy() if len(merged_from) > 1 else [],
                        )
                    )
                    current = seg
                    merged_from = [seg.uid]

            # Ajout du dernier segment
            merged.append(
                MergedSegment(
                    start=current.start,
                    end=current.end,
                    description=current.description.strip(),
                    keywords=current.keywords,
                    confidence=current.confidence,
                    merged_from=merged_from.copy() if len(merged_from) > 1 else [],
                )
            )

            return merged

        except Exception as exc:
            raise CutMindError(
                "❌ Erreur lors du process de merge.",
                code=ErrCode.FFMPEG,
                ctx=get_step_ctx({"merged_from": merged_from, "current": current}),
            ) from exc
