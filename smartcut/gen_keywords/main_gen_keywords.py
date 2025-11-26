""" """

from __future__ import annotations

from pathlib import Path

from transformers import (
    PreTrainedModel,
    ProcessorMixin,
)

from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from smartcut.gen_keywords.generate_keywords import generate_keywords_from_frames
from smartcut.models_sc.ai_result import AIResult


@with_child_logger
def generate_keywords_for_segment(
    segment_id: str,
    frame_dir: Path,
    processor: ProcessorMixin,
    model: PreTrainedModel,
    num_frames: int,
    logger: LoggerProtocol | None = None,
) -> AIResult:
    """
    Génère et fusionne les mots-clés à partir de plusieurs frames d'un segment.
    """
    logger = ensure_logger(logger, __name__)
    response: AIResult = generate_keywords_from_frames(
        frame_dir, processor, model, segment_id, num_frames, prompt_name="keywords", logger=logger
    )

    return response
