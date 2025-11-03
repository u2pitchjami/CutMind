""" """

from __future__ import annotations

from pathlib import Path

from transformers import (
    PreTrainedModel,
    ProcessorMixin,
)

from shared.utils.logger import get_logger
from smartcut.gen_keywords.generate_keywords import generate_keywords_from_frames
from smartcut.models_sc.ai_result import AIResult

logger = get_logger(__name__)


def generate_keywords_for_segment(
    segment_id: str,
    frame_dir: Path,
    processor: ProcessorMixin,
    model: PreTrainedModel,
    num_frames: int,
) -> AIResult:
    """
    Génère et fusionne les mots-clés à partir de plusieurs frames d'un segment.
    """
    response: AIResult = generate_keywords_from_frames(
        frame_dir, processor, model, segment_id, num_frames, prompt_name="keywords"
    )

    # responses = [r1, r2]
    # result = "\n".join([f"Réponse {i+1}: {r}" for i, r in enumerate(responses)])

    return response
