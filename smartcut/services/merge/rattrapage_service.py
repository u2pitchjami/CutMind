from __future__ import annotations

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from validation.services.merge_executor import MergedSegment, keyword_similarity


class PostMergeRattrapage:
    """
    Rattrape les segments trop courts en tentant de les fusionner
    avec leurs voisins contigus.

    La fusion est autorisée si :
    - la similarité sémantique atteint le seuil configuré ;
    - la durée résultante ne dépasse pas max_duration.
    """

    CONTIGUITY_TOLERANCE = 0.01

    def __init__(
        self,
        min_duration: float,
        max_duration: float,
        threshold: float = 0.5,
    ) -> None:
        if min_duration <= 0.0:
            raise ValueError("min_duration doit être > 0")

        if max_duration <= min_duration:
            raise ValueError("max_duration doit être > min_duration")

        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold doit être compris entre 0 et 1")

        self.min_duration = min_duration
        self.max_duration = max_duration
        self.threshold = threshold

    def apply(self, segments: list[MergedSegment]) -> list[MergedSegment]:
        if not segments:
            return []

        fixed: list[MergedSegment] = []
        index = 0

        try:
            while index < len(segments):
                segment = segments[index]
                duration = segment.end - segment.start

                if duration >= self.min_duration:
                    fixed.append(segment)
                    index += 1
                    continue

                previous = fixed[-1] if fixed else None
                next_segment = segments[index + 1] if index + 1 < len(segments) else None

                merged = False

                # 1. Tentative de fusion avec le précédent.
                if previous is not None and abs(segment.start - previous.end) < self.CONTIGUITY_TOLERANCE:
                    similarity = keyword_similarity(
                        previous.keywords,
                        segment.keywords,
                    )
                    new_duration = segment.end - previous.start

                    if similarity >= self.threshold and new_duration <= self.max_duration:
                        previous.end = segment.end
                        previous.description = (f"{previous.description} {segment.description}").strip()
                        previous.keywords = sorted(set(previous.keywords + segment.keywords))
                        previous.confidence = max(
                            previous.confidence,
                            segment.confidence,
                        )
                        previous.merged_from.extend(segment.merged_from)

                        merged = True

                if merged:
                    index += 1
                    continue

                # 2. Si la gauche a échoué, tentative avec le suivant.
                if next_segment is not None and abs(next_segment.start - segment.end) < self.CONTIGUITY_TOLERANCE:
                    similarity = keyword_similarity(
                        segment.keywords,
                        next_segment.keywords,
                    )
                    new_duration = next_segment.end - segment.start

                    if similarity >= self.threshold and new_duration <= self.max_duration:
                        new_segment = MergedSegment(
                            start=segment.start,
                            end=next_segment.end,
                            description=(f"{segment.description} {next_segment.description}").strip(),
                            keywords=sorted(set(segment.keywords + next_segment.keywords)),
                            confidence=max(
                                segment.confidence,
                                next_segment.confidence,
                            ),
                            merged_from=(segment.merged_from + next_segment.merged_from),
                        )

                        fixed.append(new_segment)

                        # segment + next_segment ont été consommés.
                        index += 2
                        continue

                # Aucun merge possible pour le moment.
                fixed.append(segment)
                index += 1

            return fixed

        except CutMindError as err:
            raise err.with_context(
                get_step_ctx(
                    {
                        "segment_count": len(segments),
                        "processed_count": index,
                    }
                )
            ) from err

        except Exception as exc:
            raise CutMindError(
                "Erreur inattendue lors du rattrapage merge SmartCut.",
                code=ErrCode.UNEXPECTED,
                ctx=get_step_ctx(
                    {
                        "segment_count": len(segments),
                        "processed_count": index,
                    }
                ),
            ) from exc
