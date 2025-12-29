from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from transformers import PreTrainedModel, ProcessorMixin

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from smartcut.models_sc.ai_result import AIResult
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
) -> AIResult:
    """
    Traite un segment vidéo par lots et récupère les descriptions + mots-clés IA.
    """
    try:
        batch_result_raw = generate_keywords_for_segment(
            segment_id=f"{video_name}_seg_{int(start * 10)}_{int(end * 10)}",
            frame_dir=batch_dir,
            processor=processor,
            model=model,
            num_frames=len(batch_paths),
        )

        parsed_result: AIResult = {"description": "", "keywords": []}
        print(f"Batch result: {type(batch_result_raw)}")

        if isinstance(batch_result_raw, str):
            parsed = json.loads(batch_result_raw)
            if isinstance(parsed, dict):
                # normaliser les clés
                lower = {k.lower(): v for k, v in parsed.items()}
                parsed_result["description"] = str(lower.get("description", ""))
                parsed_result["keywords"] = list(lower.get("keywords", []))
            else:
                parsed_result["keywords"] = [kw.strip() for kw in str(parsed).split(",") if kw.strip()]

        elif isinstance(batch_result_raw, dict):
            lower2: dict[str, Any] = {k.lower(): v for k, v in batch_result_raw.items()}
            parsed_result["description"] = str(lower2.get("description", ""))
            # ✅ Cast explicite pour que mypy voie bien une liste de str
            raw_keywords = lower2.get("keywords", [])
            if isinstance(raw_keywords, list):
                parsed_result["keywords"] = [str(kw).strip() for kw in raw_keywords if str(kw).strip()]
            elif isinstance(raw_keywords, str):
                parsed_result["keywords"] = [kw.strip() for kw in raw_keywords.split(",") if kw.strip()]
            else:
                parsed_result["keywords"] = []
    except CutMindError as err:
        raise err.with_context(get_step_ctx({"video name": video_name})) from err
    except json.JSONDecodeError:
        # ✅ Ici on force le type en str pour mypy
        raw_text = cast(str, batch_result_raw)
        parsed_result["keywords"] = [kw.strip() for kw in raw_text.split(",") if kw.strip()]
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur lors du traitement IA.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video name": video_name}),
        ) from exc
    return parsed_result
