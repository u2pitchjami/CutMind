from __future__ import annotations

from pathlib import Path

from transformers import PreTrainedModel, ProcessorMixin

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from smartcut.models_sc.ai_result import AIOutputType, AIResult
from smartcut.services.main_gen_keywords import generate_keywords_for_segment

KeywordsBatches = list[AIResult]


# ===========================================================
# ⚙️ FONCTION DE TRAITEMENT PAR LOTS (batches)
# ===========================================================


def process_batches(
    video_name: str,
    start: float,
    end: float,
    frame_paths: list[str],
    batch_size: int,
    batch_dir: Path,
    batch_paths: list[str],
    processor: ProcessorMixin,
    model: PreTrainedModel,
    prompt_name: str = "keywords",
    system_prompt: str = "system_keywords",
    output_type: AIOutputType = "full",
) -> AIResult:
    """
    Traite un segment vidéo par lots et récupère la sortie IA selon le type.
    """
    try:
        segment_id = f"{video_name}_seg_{int(start * 10)}_{int(end * 10)}"

        result = generate_keywords_for_segment(
            segment_id=segment_id,
            frame_dir=batch_dir,
            processor=processor,
            model=model,
            num_frames=len(batch_paths),
            prompt_name=prompt_name,
            system_prompt=system_prompt,
            output_type=output_type,
        )

        return result

    except CutMindError as err:
        raise err.with_context(get_step_ctx({"video name": video_name})) from err

    except Exception as exc:
        raise CutMindError(
            "❌ Erreur lors du traitement IA.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video name": video_name}),
        ) from exc
