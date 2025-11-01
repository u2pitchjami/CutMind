""" """

from __future__ import annotations

from pathlib import Path

from transformers import (
    PreTrainedModel,
    ProcessorMixin,
)

from shared.utils.logger import get_logger
from smartcut.gen_keywords.generate_keywords import generate_keywords_from_frames

logger = get_logger(__name__)


def generate_keywords_for_segment(
    segment_id: str,
    frame_dir: Path,
    processor: ProcessorMixin,
    model: PreTrainedModel,
    num_frames: int,
) -> str:
    """
    Génère et fusionne les mots-clés à partir de plusieurs frames d'un segment.
    """
    response: str = generate_keywords_from_frames(frame_dir, processor, model, segment_id, num_frames)

    return response
