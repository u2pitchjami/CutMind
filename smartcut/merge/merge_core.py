""" """

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from shared.models.smartcut_model import Segment
from shared.utils.logger import get_logger
from smartcut.merge.merge_utils import keyword_similarity

logger = get_logger(__name__)


def merge_similar_segments_optimized_v2(
    segments: list[Segment],
    threshold: float = 0.5,
    min_duration: float = 15.0,
    max_duration: float = 120.0,
    rattrapage: bool = True,
) -> list[Segment]:
    """
    Version enrichie : fusionne les segments similaires tout en gérant les identifiants (id, uid) et la traçabilité.
    """
    if not segments:
        logger.warning("Aucun segment à traiter.")
        return []

    merged: list[Segment] = []
    current = Segment(
        id=segments[0].id,
        start=segments[0].start,
        end=segments[0].end,
        keywords=list(segments[0].keywords),
        ai_status=segments[0].ai_status,
    )
    current.compute_duration()
    current.merged_from = [segments[0].uid] if hasattr(segments[0], "uid") else []
    logger.debug(f"current.keywords : {type(current.keywords)} : {current.keywords[:50]}")

    # --- 🧩 Étape 1 : fusion sémantique ---
    for seg in segments[1:]:
        seg.compute_duration()
        sim = keyword_similarity(current.keywords, seg.keywords)
        new_duration = seg.end - current.start

        if sim >= threshold and new_duration <= max_duration:
            logger.debug(
                "Fusion segments (%.2fs→%.2fs) [%.2fs total] — %s + %s",
                current.start,
                seg.end,
                new_duration,
                current.keywords,
                seg.keywords,
            )
            current.end = seg.end
            current.duration = new_duration
            current.keywords = sorted(set(current.keywords) | set(seg.keywords))
            if hasattr(seg, "uid"):
                current.merged_from.append(seg.uid)
        else:
            # 🆕 Nouveau segment (avec UID automatique)
            merged.append(current)
            current = Segment(
                id=seg.id,
                start=seg.start,
                end=seg.end,
                keywords=list(seg.keywords),
                ai_status=seg.ai_status,
            )
            current.compute_duration()
            current.merged_from = [seg.uid] if hasattr(seg, "uid") else []

    merged.append(current)

    # --- 🧩 Étape 2 : rattrapage optionnel ---
    if not rattrapage:
        final_segments: list[Segment] = merged
    else:
        final_segments = []
        for i, seg in enumerate(merged):
            seg.compute_duration()
            if seg.duration is not None and seg.duration < min_duration:
                prev_seg = final_segments[-1] if final_segments else None
                next_seg = merged[i + 1] if i + 1 < len(merged) else None
                merged_with = False

                # 🔹 Fusion avec précédent
                if prev_seg and abs(seg.start - prev_seg.end) < 0.01:
                    sim = keyword_similarity(prev_seg.keywords, seg.keywords)
                    new_dur = seg.end - prev_seg.start
                    if sim >= threshold and new_dur <= max_duration:
                        prev_seg.end = seg.end
                        prev_seg.duration = new_dur
                        prev_seg.keywords = sorted(set(prev_seg.keywords) | set(seg.keywords))
                        if hasattr(seg, "uid"):
                            prev_seg.merged_from.append(seg.uid)
                        merged_with = True

                # 🔹 Fusion avec suivant
                elif next_seg and abs(next_seg.start - seg.end) < 0.01:
                    sim = keyword_similarity(seg.keywords, next_seg.keywords)
                    new_dur = next_seg.end - seg.start
                    if sim >= threshold and new_dur <= max_duration:
                        seg.end = next_seg.end
                        seg.duration = new_dur
                        seg.keywords = sorted(set(seg.keywords) | set(next_seg.keywords))
                        if hasattr(next_seg, "uid"):
                            seg.merged_from.append(next_seg.uid)
                        merged_with = True
                        merged[i + 1] = seg

                if not merged_with:
                    final_segments.append(seg)
            else:
                final_segments.append(seg)

    # --- 🧩 Étape 3 : réindexation + nouvel UID ---
    for i, seg in enumerate(final_segments, start=1):
        seg.id = i
        seg.uid = str(uuid4())  # 🆕 UID unique pour le segment fusionné
        seg.last_updated = datetime.now().isoformat()

    logger.info("Fusion terminée : %d segments initiaux → %d segments finaux", len(segments), len(final_segments))
    return final_segments
