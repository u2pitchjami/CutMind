"""Segment selection engine for CutMind compilations."""

from __future__ import annotations

from datetime import datetime, timedelta
import random

from compil.compilation_template import CompilationBlock
from db.db_connection import db_conn, get_dict_cursor
from db.repository import CutMindRepository
from shared.models.db_models import Segment
from shared.utils.logger import LoggerProtocol, ensure_logger


def _segment_duration(segment: Segment) -> float:
    """Return a safe positive duration for a segment."""
    duration = segment.duration

    if duration is None or duration <= 0:
        return 0.0

    return float(duration)


def _is_recent(
    segment: Segment,
    threshold: datetime | None,
) -> bool:
    """Return whether a segment satisfies the recent constraint."""
    if threshold is None or segment.created_at is None:
        return False

    return segment.created_at >= threshold


def _selected_duration(segments: list[Segment]) -> float:
    return sum(_segment_duration(segment) for segment in segments)


def _keyword_value(
    segments: list[Segment],
    keyword: str,
    duration_mode: bool,
) -> float:
    """Return current contribution to a keyword constraint."""
    matching = [segment for segment in segments if keyword in segment.keywords]

    if duration_mode:
        return _selected_duration(matching)

    return float(len(matching))


def _recent_value(
    segments: list[Segment],
    threshold: datetime | None,
    duration_mode: bool,
) -> float:
    """Return current contribution to the recent constraint."""
    matching = [segment for segment in segments if _is_recent(segment, threshold)]

    if duration_mode:
        return _selected_duration(matching)

    return float(len(matching))


def _candidate_score(
    segment: Segment,
    block: CompilationBlock,
    selected: list[Segment],
    recent_threshold: datetime | None,
) -> int:
    """
    Score a candidate according to currently unsatisfied constraints.

    A segment satisfying multiple missing constraints receives a higher score.
    """
    score = 0
    duration_mode = block.duration is not None

    target_value = float(block.duration) if block.duration is not None else float(block.count or 0)

    for rule in block.keyword_rules:
        target = target_value * rule.ratio

        current = _keyword_value(
            selected,
            rule.keyword,
            duration_mode,
        )

        if current < target and rule.keyword in segment.keywords:
            score += 1

    if block.recent_ratio > 0.0:
        recent_target = target_value * block.recent_ratio

        current_recent = _recent_value(
            selected,
            recent_threshold,
            duration_mode,
        )

        if current_recent < recent_target and _is_recent(segment, recent_threshold):
            score += 1

    return score


def _choose_candidate(
    candidates: list[Segment],
    block: CompilationBlock,
    selected: list[Segment],
    recent_threshold: datetime | None,
) -> Segment:
    """
    Choose a candidate while favoring unsatisfied constraints.

    Random selection is preserved between equally useful candidates.
    """
    scored = [
        (
            _candidate_score(
                segment,
                block,
                selected,
                recent_threshold,
            ),
            segment,
        )
        for segment in candidates
    ]

    best_score = max(score for score, _ in scored)

    best_candidates = [segment for score, segment in scored if score == best_score]

    return random.choice(best_candidates)


def _select_by_count(
    candidates: list[Segment],
    block: CompilationBlock,
    recent_threshold: datetime | None,
) -> list[Segment]:
    """Select segments until the requested count is reached."""
    if block.count is None:
        return []

    selected: list[Segment] = []
    remaining = list(candidates)

    while remaining and len(selected) < block.count:
        chosen = _choose_candidate(
            candidates=remaining,
            block=block,
            selected=selected,
            recent_threshold=recent_threshold,
        )

        selected.append(chosen)
        remaining.remove(chosen)

    return selected


def _select_by_duration(
    candidates: list[Segment],
    block: CompilationBlock,
    recent_threshold: datetime | None,
    max_overflow_ratio: float,
    logger: LoggerProtocol,
) -> list[Segment]:
    """Select segments while respecting the duration overflow limit."""
    if block.duration is None:
        return []

    target_duration = float(block.duration)

    max_duration = target_duration * (1.0 + max_overflow_ratio)

    valid_candidates = [segment for segment in candidates if _segment_duration(segment) > 0.0]

    if not valid_candidates:
        return []

    # Avoid the pathological case:
    # target=30 seconds, first segment=180 seconds.
    candidates_within_limit = [segment for segment in valid_candidates if _segment_duration(segment) <= max_duration]

    if not candidates_within_limit:
        shortest = min(
            valid_candidates,
            key=_segment_duration,
        )

        logger.warning(
            "⚠️ Aucun segment ne respecte la durée maximale %.1fs "
            "pour une cible de %.1fs. "
            "Sélection exceptionnelle du segment le plus court : %.1fs.",
            max_duration,
            target_duration,
            _segment_duration(shortest),
        )

        return [shortest]

    selected: list[Segment] = []
    remaining = list(candidates_within_limit)

    while remaining:
        current_duration = _selected_duration(selected)

        if current_duration >= target_duration:
            break

        allowed = [segment for segment in remaining if (current_duration + _segment_duration(segment) <= max_duration)]

        if not allowed:
            break

        chosen = _choose_candidate(
            candidates=allowed,
            block=block,
            selected=selected,
            recent_threshold=recent_threshold,
        )

        selected.append(chosen)
        remaining.remove(chosen)

    return selected


def select_segments_for_block(
    block: CompilationBlock,
    repo: CutMindRepository,
    used_uids: set[str],
    max_overflow_ratio: float = 0.25,
    logger: LoggerProtocol | None = None,
) -> list[Segment]:
    """Select segments satisfying a compilation block."""
    logger = ensure_logger(logger, __name__)

    segments = repo.get_segments_by_category(
        block.category,
        ["validated_check"],
    )

    logger.debug(
        "Block '%s': %d segments trouvés.",
        block.category,
        len(segments),
    )

    with db_conn(logger=logger) as conn:
        with get_dict_cursor(conn) as cursor:
            for segment in segments:
                if segment.id is None:
                    continue

                segment.keywords = repo.get_keywords_for_segment(
                    cursor,
                    segment.id,
                )

    candidates = [
        segment
        for segment in segments
        if (segment.uid not in used_uids and not any(keyword in block.keywords_exclude for keyword in segment.keywords))
    ]

    if not candidates:
        logger.warning(
            "⚠️ Block '%s': aucun segment disponible.",
            block.category,
        )
        return []

    recent_threshold: datetime | None = None

    if block.recent_days is not None:
        recent_threshold = datetime.now() - timedelta(days=block.recent_days)

    if block.count is not None:
        selected = _select_by_count(
            candidates=candidates,
            block=block,
            recent_threshold=recent_threshold,
        )

    else:
        selected = _select_by_duration(
            candidates=candidates,
            block=block,
            recent_threshold=recent_threshold,
            max_overflow_ratio=max_overflow_ratio,
            logger=logger,
        )

    used_uids.update(segment.uid for segment in selected)

    total_duration = _selected_duration(selected)

    logger.info(
        "✅ Block '%s': %d segments sélectionnés, %.1f secondes.",
        block.category,
        len(selected),
        total_duration,
    )

    return selected
