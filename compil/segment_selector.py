from datetime import datetime, timedelta
import random

from compil.compilation_template import CompilationBlock
from db.db_connection import db_conn, get_dict_cursor
from db.repository import CutMindRepository
from shared.models.db_models import Segment
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger


@with_child_logger
def select_segments_for_block(
    block: CompilationBlock, repo: CutMindRepository, logger: LoggerProtocol | None = None
) -> list[Segment]:
    logger = ensure_logger(logger, __name__)
    segments = repo.get_segments_by_category(block.category, ["validated_check"])
    logger.info("🔍 Sélection segments pour block '%s' : %d segments trouvés", block.category, len(segments))
    with db_conn(logger=logger) as conn:
        with get_dict_cursor(conn) as cur:
            for seg in segments:
                if not seg.id:
                    continue
                seg.keywords = repo.get_keywords_for_segment(cur, seg.id)
    # --- Étape 1 : filtre strict keywords_exclude
    segments = [s for s in segments if not any(keyword in block.keywords_exclude for keyword in s.keywords)]
    logger.info("🔍 Après filtre keywords_exclude : %d segments restants", len(segments))

    if not segments:
        return []

    total_count_target = block.count
    total_duration_target = block.duration
    selected: list[Segment] = []
    used_uids: set[str] = set()

    # --- Étape 2 : séparer récents / anciens
    recent_segments, other_segments = [], []
    if block.recent_days:
        threshold = datetime.now() - timedelta(days=block.recent_days)
        for seg in segments:
            if seg.created_at and seg.created_at >= threshold:
                recent_segments.append(seg)
            else:
                other_segments.append(seg)
    else:
        other_segments = segments

    # --- Étape 3 : appliquer les keyword_rules
    if block.keyword_rules:
        for rule in block.keyword_rules:
            keyword_matches = [s for s in segments if rule.keyword in s.keywords and s.uid not in used_uids]
            logger.info("🔍 Keyword rule '%s' : %d segments correspondants", rule.keyword, len(keyword_matches))

            if total_count_target:
                count_target = int(total_count_target * rule.ratio)
                logger.info("🔍 Keyword rule '%s' : cible %d segments", rule.keyword, count_target)
                chosen = random.sample(keyword_matches, min(count_target, len(keyword_matches)))
                logger.info("🔍 Keyword rule '%s' : sélection %d segments", rule.keyword, len(chosen))
            elif total_duration_target:
                logger.info(
                    "🔍 Keyword rule '%s' : cible %f secondes", rule.keyword, total_duration_target * rule.ratio
                )
                chosen = accumulate_until_duration(keyword_matches, total_duration_target * rule.ratio, used_uids)
                logger.info("🔍 Keyword rule '%s' : sélection %d segments", rule.keyword, len(chosen))
            else:
                continue

            selected.extend(chosen)
            used_uids.update(s.uid for s in chosen)

    # --- Étape 4 : ajouter segments récents selon ratio
    if block.recent_ratio > 0 and recent_segments:
        logger.info("🔍 Recent segments : %d segments correspondants", len(recent_segments))
        remaining_count = (total_count_target - len(selected)) if total_count_target else None
        logger.info("🔍 Recent segments : cible %d segments", remaining_count if remaining_count else 0)
        remaining_duration = (
            total_duration_target - sum(s.duration or 0 for s in selected) if total_duration_target else None
        )
        logger.info("🔍 Recent segments : cible %f secondes", float(remaining_duration) if remaining_duration else 0)
        recent_target_count = int((total_count_target or 0) * block.recent_ratio)
        recent_target_duration = (total_duration_target or 0) * block.recent_ratio
        logger.info("🔍 Recent segments : cible %d segments (ratio %.2f)", recent_target_count, block.recent_ratio)

        recent_pool = [s for s in recent_segments if s.uid not in used_uids]

        if total_count_target:
            logger.info("🔍 Recent segments : cible %d segments", recent_target_count)
            chosen = random.sample(recent_pool, min(recent_target_count, len(recent_pool)))
        elif total_duration_target:
            logger.info("🔍 Recent segments : cible %f secondes", recent_target_duration)
            chosen = accumulate_until_duration(recent_pool, recent_target_duration, used_uids)
        else:
            chosen = []

        selected.extend(chosen)
        used_uids.update(s.uid for s in chosen)

    # --- Étape 5 : compléter avec segments restants si besoin
    remaining_count = (total_count_target - len(selected)) if total_count_target else None
    logger.info("🔍 Segments restants : cible %d segments", remaining_count if remaining_count else 0)
    remaining_duration = (
        total_duration_target - sum(s.duration or 0 for s in selected) if total_duration_target else None
    )
    logger.info("🔍 Segments restants : cible %f secondes", float(remaining_duration) if remaining_duration else 0)

    if (remaining_count and remaining_count > 0) or (remaining_duration and remaining_duration > 0):
        logger.info("🔍 Segments restants : besoin de compléter avec segments restants")
        fallback_pool = [s for s in segments if s.uid not in used_uids]
        logger.info("🔍 Fallback segments : %d segments correspondants", len(fallback_pool))

        if total_count_target and remaining_count:
            logger.info("🔍 Fallback segments : cible %d segments", remaining_count)
            count = min(remaining_count, len(fallback_pool))
            logger.info("🔍 Fallback segments : cible %d segments", count)
            selected += random.sample(fallback_pool, count)

        elif total_duration_target and remaining_duration:
            logger.info("🔍 Fallback segments : cible %f secondes", float(remaining_duration))
            duration = float(remaining_duration)
            selected += accumulate_until_duration(fallback_pool, duration, used_uids)
            logger.info("🔍 Fallback segments : sélection %d segments", len(selected))

    return selected


def accumulate_until_duration(segments: list[Segment], target_duration: float, used_uids: set[str]) -> list[Segment]:
    """
    Sélectionne aléatoirement des segments jusqu'à atteindre `target_duration` (en secondes).
    """
    random.shuffle(segments)
    selected = []
    total = 0.0

    for seg in segments:
        if seg.uid in used_uids:
            continue
        dur = seg.duration or 0
        if total + dur > target_duration:
            break
        selected.append(seg)
        total += dur
        used_uids.add(seg.uid)

    return selected
