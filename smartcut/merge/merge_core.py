""" """

from __future__ import annotations

from datetime import datetime
import uuid

from shared.utils.logger import get_logger
from smartcut.merge.merge_utils import keyword_similarity
from smartcut.models_sc.smartcut_model import Segment

logger = get_logger(__name__)


def merge_similar_segments_optimized_v2(
    segments: list[Segment],
    threshold: float = 0.5,
    gap_confidence: float = 0.25,
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
        description=segments[0].description,
        keywords=list(segments[0].keywords),
        ai_status=segments[0].ai_status,
        confidence=segments[0].confidence,
    )
    current.compute_duration()
    current.merged_from = [segments[0].uid] if hasattr(segments[0], "uid") else []
    logger.debug(f"current.keywords : {type(current.keywords)} : {current.keywords[:50]}")

    # --- 🧩 Étape 1 : fusion sémantique ---
    for seg in segments[1:]:
        seg.compute_duration()
        sim = keyword_similarity(current.keywords, seg.keywords)
        new_duration = seg.end - current.start
        if current.confidence is not None and seg.confidence is not None:
            conf_gap = abs(current.confidence - seg.confidence)
        else:
            conf_gap = 0.0

        if sim >= threshold and new_duration <= max_duration and conf_gap < gap_confidence:
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
            all_descriptions = [current.description, seg.description]
            current.description = " ".join(all_descriptions).strip()
            if hasattr(seg, "uid"):
                current.merged_from.append(seg.uid)
            if current.confidence is not None and seg.confidence is not None:
                merged_conf = (current.confidence + seg.confidence) / 2
                current.confidence = round(merged_conf, 3)

        else:
            # 🆕 Nouveau segment (avec UID automatique)
            merged.append(current)
            current = Segment(
                id=seg.id,
                start=seg.start,
                end=seg.end,
                description=seg.description,
                keywords=list(seg.keywords),
                confidence=seg.confidence,
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
                        all_descriptions = [prev_seg.description, seg.description]
                        prev_seg.description = " ".join(all_descriptions).strip()
                        if hasattr(seg, "uid"):
                            prev_seg.merged_from.append(seg.uid)
                        if prev_seg.confidence is not None and seg.confidence is not None:
                            merged_conf = (prev_seg.confidence + seg.confidence) / 2
                            prev_seg.confidence = round(merged_conf, 3)
                        merged_with = True

                # 🔹 Fusion avec suivant
                elif next_seg and abs(next_seg.start - seg.end) < 0.01:
                    sim = keyword_similarity(seg.keywords, next_seg.keywords)
                    new_dur = next_seg.end - seg.start
                    if sim >= threshold and new_dur <= max_duration:
                        seg.end = next_seg.end
                        seg.duration = new_dur
                        seg.keywords = sorted(set(seg.keywords) | set(next_seg.keywords))
                        all_descriptions = [seg.description, next_seg.description]
                        seg.description = " ".join(all_descriptions).strip()
                        if hasattr(next_seg, "uid"):
                            seg.merged_from.append(next_seg.uid)
                        if seg.confidence is not None and next_seg.confidence is not None:
                            merged_conf = (seg.confidence + next_seg.confidence) / 2
                            seg.confidence = round(merged_conf, 3)
                        merged_with = True
                        merged[i + 1] = seg

                if not merged_with:
                    final_segments.append(seg)
            else:
                final_segments.append(seg)

    # --- 🧩 Étape 3 : réindexation + nouvel UID ---
    for i, seg in enumerate(final_segments, start=1):
        seg.id = i
        seg.uid = str(uuid.uuid4())  # 🆕 UID unique pour le segment fusionné
        seg.last_updated = datetime.now().isoformat()

    logger.info("Fusion terminée : %d segments initiaux → %d segments finaux", len(segments), len(final_segments))
    return final_segments
