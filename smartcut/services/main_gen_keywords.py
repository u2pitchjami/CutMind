""" """

from __future__ import annotations

from pathlib import Path

from transformers import (
    PreTrainedModel,
    ProcessorMixin,
)

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.logger import LoggerProtocol
from smartcut.executors.ia.generate_keywords import generate_keywords_from_frames
from smartcut.models_sc.ai_result import AIResult


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
    try:
        response: AIResult = generate_keywords_from_frames(
            frame_dir, processor, model, segment_id, num_frames, prompt_name="keywords", system_prompt="system_keywords"
        )
        return response
    except CutMindError as err:
        raise err.with_context(get_step_ctx({"segment_id": segment_id})) from err
    except Exception as exc:
        raise CutMindError(
            "Erreur lors du traitement IA.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"segment_id": segment_id}),
        ) from exc
