""" """

from __future__ import annotations

from shared.models.config_manager import CONFIG
from shared.models.smartcut_model import SmartCutSession
from shared.utils.logger import get_logger
from smartcut.merge.merge_core import merge_similar_segments_optimized_v2

logger = get_logger(__name__)

THRESHOLD = CONFIG.smartcut["merge"]["threshold"]
RATTRAPAGE = CONFIG.smartcut["merge"]["rattrapage"]


def process_result(
    result: SmartCutSession,
    min_duration: float = 15.0,
    max_duration: float = 180.0,
) -> SmartCutSession:
    """
    Fusionne les segments similaires et met à jour la session SmartCut.
    """
    merged_segments = merge_similar_segments_optimized_v2(
        result.segments,
        threshold=THRESHOLD,
        min_duration=min_duration,
        max_duration=max_duration,
        rattrapage=RATTRAPAGE,
    )

    # 🧠 Met à jour la session avec les segments fusionnés
    result.segments = merged_segments
    result.status = "merged"

    logger.info(f"✅ Fusion terminée : {len(merged_segments)} segments restants pour {result.video}")

    return result
