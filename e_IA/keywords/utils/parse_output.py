"""
Extraction de mots-clés pour un segment vidéo via Qwen3-VL-4B-Thinking-abliterated (Hugging Face), avec les mêmes
paramètres que le node ComfyUI.
"""

from __future__ import annotations

import json

from e_IA.keywords.utils.ai_result import AIOutputType, AIResult
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx


def parse_json_ai_output(
    decoded_text: str,
    output_type: AIOutputType,
) -> AIResult:
    try:
        data = json.loads(decoded_text)

        if not isinstance(data, dict):
            raise CutMindError(
                "❌ AI output is not a JSON object.",
                code=ErrCode.IAERROR,
                ctx=get_step_ctx({"decoded_text": decoded_text}),
            )

        result: AIResult = {}

        if output_type == AIOutputType.SCENE_ANALYSIS:
            description = data.get("description")
            if isinstance(description, str) and description.strip():
                result["description"] = description.strip()

            keywords = data.get("keywords")
            if isinstance(keywords, list):
                result["keywords"] = [str(k).strip() for k in keywords if str(k).strip()]

        elif output_type == AIOutputType.SCENE_RATING:
            quality = data.get("quality_rating")
            interest = data.get("interest_rating")

            if isinstance(quality, (int | float)) and isinstance(interest, (int | float)):
                quality_f = max(1.0, min(5.0, float(quality)))
                interest_f = max(1.0, min(5.0, float(interest)))

                result["quality_rating"] = quality_f
                result["interest_rating"] = interest_f

        else:
            raise CutMindError(
                f"❌ Unsupported AI output type: {output_type}",
                code=ErrCode.IAERROR,
                ctx=get_step_ctx(),
            )

        return result

    except json.JSONDecodeError as exc:
        raise CutMindError(
            "❌ Model did not return valid JSON.",
            code=ErrCode.IAERROR,
            ctx=get_step_ctx({"decoded_text": decoded_text}),
        ) from exc
