from __future__ import annotations

from smartcut.executors.merge_executor import MergedSegment, keyword_similarity


class PostMergeRattrapage:
    """
    Rattrape les segments trop courts en tentant de les fusionner
    avec leurs voisins (avant ou après) si les règles le permettent.
    """

    def __init__(self, min_duration: float, max_duration: float, threshold: float = 0.5):
        self.min_duration = min_duration
        self.max_duration = max_duration
        self.threshold = threshold
        print(
            f"PostMergeRattrapage: min_duration={self.min_duration}, max_duration={self.max_duration},\
                threshold={self.threshold}"
        )

    def apply(self, segments: list[MergedSegment]) -> list[MergedSegment]:
        if not segments:
            return []

        fixed: list[MergedSegment] = []

        i = 0
        while i < len(segments):
            seg = segments[i]
            duration = seg.end - seg.start

            if duration >= self.min_duration:
                fixed.append(seg)
                i += 1
                continue

            # Essayer de fusionner avec le précédent
            prev = fixed[-1] if fixed else None
            next_seg = segments[i + 1] if i + 1 < len(segments) else None

            merged = False

            # ➕ Fusion avec précédent
            if prev and abs(seg.start - prev.end) < 0.01:
                sim = keyword_similarity(prev.keywords, seg.keywords)
                new_duration = seg.end - prev.start
                if sim >= self.threshold and new_duration <= self.max_duration:
                    prev.end = seg.end
                    prev.description += " " + seg.description
                    prev.keywords = sorted(set(prev.keywords + seg.keywords))
                    prev.confidence = max(prev.confidence, seg.confidence)
                    prev.merged_from.extend(seg.merged_from)
                    merged = True

            # ➕ Fusion avec suivant
            elif next_seg and abs(next_seg.start - seg.end) < 0.01:
                sim = keyword_similarity(seg.keywords, next_seg.keywords)
                new_duration = next_seg.end - seg.start
                if sim >= self.threshold and new_duration <= self.max_duration:
                    new_seg = MergedSegment(
                        start=seg.start,
                        end=next_seg.end,
                        description=seg.description + " " + next_seg.description,
                        keywords=sorted(set(seg.keywords + next_seg.keywords)),
                        confidence=max(seg.confidence, next_seg.confidence),
                        merged_from=seg.merged_from + next_seg.merged_from,
                    )
                    fixed.append(new_seg)
                    i += 2  # skip next_seg
                    merged = True

            if not merged:
                fixed.append(seg)

            i += 1

        return fixed
