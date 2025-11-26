from __future__ import annotations

from dataclasses import dataclass


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


class MergeExecutor:
    """
    Exécuteur pur : fusionne les segments adjacents selon des règles simples.
    Aucune logique SmartCut, aucune session, aucune file IO.
    """

    def merge(self, segments: list[RawSegment]) -> list[MergedSegment]:
        if not segments:
            return []

        # trier par start
        segments = sorted(segments, key=lambda s: s.start)

        merged: list[MergedSegment] = []
        current = segments[0]
        merged_from = [current.uid]

        for seg in segments[1:]:
            if abs(seg.start - current.end) < 0.5:
                current = RawSegment(
                    start=current.start,
                    end=seg.end,
                    description=current.description + " " + seg.description,
                    keywords=list(set(current.keywords + seg.keywords)),
                    confidence=max(current.confidence, seg.confidence),
                    uid=current.uid,
                )
                merged_from.append(seg.uid)

            else:
                merged.append(
                    MergedSegment(
                        start=current.start,
                        end=current.end,
                        description=current.description.strip(),
                        keywords=current.keywords,
                        confidence=current.confidence,
                        merged_from=merged_from.copy(),
                    )
                )
                current = seg
                merged_from = [seg.uid]

        merged.append(
            MergedSegment(
                start=current.start,
                end=current.end,
                description=current.description.strip(),
                keywords=current.keywords,
                confidence=current.confidence,
                merged_from=merged_from.copy(),
            )
        )

        return merged
