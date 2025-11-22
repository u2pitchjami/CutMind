""" """

from __future__ import annotations

from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from shared.utils.settings import get_settings
from smartcut.merge.merge_core import merge_similar_segments_optimized_v2
from smartcut.models_sc.smartcut_model import SmartCutSession

settings = get_settings()
THRESHOLD = settings.merge.threshold
RATTRAPAGE = settings.merge.rattrapage
GAP_CONFIDENCE = settings.merge.gap_confidence


@with_child_logger
def process_result(
    result: SmartCutSession,
    min_duration: float = 15.0,
    max_duration: float = 180.0,
    logger: LoggerProtocol | None = None,
) -> SmartCutSession:
    """
    Fusionne les segments similaires et met à jour la session SmartCut.
    """
    logger = ensure_logger(logger, __name__)
    merged_segments = merge_similar_segments_optimized_v2(
        result.segments,
        threshold=THRESHOLD,
        gap_confidence=GAP_CONFIDENCE,
        min_duration=min_duration,
        max_duration=max_duration,
        rattrapage=RATTRAPAGE,
        logger=logger,
    )

    # 🧠 Met à jour la session avec les segments fusionnés
    result.segments = merged_segments
    result.status = "merged"

    logger.info(f"✅ Fusion terminée : {len(merged_segments)} segments restants pour {result.video}")

    return result
