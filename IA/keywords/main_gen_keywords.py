""" """

from __future__ import annotations

from pathlib import Path

from transformers import (
    PreTrainedModel,
    ProcessorMixin,
)

from IA.keywords.utils.ai_result import AIOutputType, AIResult
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.logger import LoggerProtocol, ensure_logger
from shared.utils.settings import get_settings


def generate_keywords_for_segment(
    segment_id: str,
    frame_dir: Path,
    processor: ProcessorMixin | None,
    model: PreTrainedModel | None,
    num_frames: int,
    output_type: AIOutputType,
    prompt_name: str = "keywords",
    system_prompt: str = "system_keywords",
    logger: LoggerProtocol | None = None,
) -> AIResult:
    """
    Génère et fusionne les mots-clés à partir de plusieurs frames d'un segment.
    """
    try:
        logger = ensure_logger(logger, __name__)
        if get_settings().generate_keywords.backend == "ollama":
            from IA.keywords.analyze.ollama_keywords import generate_keywords_with_ollama

            return generate_keywords_with_ollama(
                frame_dir,
                segment_id,
                num_frames,
                output_type,
                prompt_name=prompt_name,
                system_prompt=system_prompt,
                logger=logger,
            )
        if processor is None or model is None:
            raise CutMindError("Modèle Transformers non chargé.", code=ErrCode.IAERROR)
        from IA.keywords.analyze.generate_keywords import generate_keywords_from_frames

        response: AIResult = generate_keywords_from_frames(
            frame_dir,
            processor,
            model,
            segment_id,
            num_frames,
            prompt_name=prompt_name,
            system_prompt=system_prompt,
            output_type=output_type,
            logger=logger,
        )
        return response
    except CutMindError as err:
        raise err.with_context(get_step_ctx({"segment_id": segment_id})) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur lors du traitement IA.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"segment_id": segment_id}),
        ) from exc
