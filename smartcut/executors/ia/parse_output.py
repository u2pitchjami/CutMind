"""
Extraction de mots-clés pour un segment vidéo via Qwen3-VL-4B-Thinking-abliterated (Hugging Face), avec les mêmes
paramètres que le node ComfyUI.
"""

from __future__ import annotations

import json
from typing import cast

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from smartcut.models_sc.ai_result import AIResult


def parse_json_ai_output(decoded_text: str) -> AIResult:
    try:
        data = json.loads(decoded_text)

        if not isinstance(data, dict):
            raise CutMindError(
                "❌ AI output is not a JSON object.",
                code=ErrCode.IAERROR,
                ctx=get_step_ctx({"decoded_text": decoded_text}),
            )

        result: dict[str, object] = {}

        description = data.get("description")
        if isinstance(description, str) and description.strip():
            result["description"] = description.strip()

        keywords = data.get("keywords")
        if isinstance(keywords, list):
            result["keywords"] = [str(k).strip() for k in keywords if str(k).strip()]

        return cast(AIResult, result)

    except json.JSONDecodeError as exc:
        raise CutMindError(
            "❌ Model did not return valid JSON.",
            code=ErrCode.IAERROR,
            ctx=get_step_ctx({"decoded_text": decoded_text}),
        ) from exc
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur lors du parsing IA.",
            code=ErrCode.IAERROR,
            ctx=get_step_ctx({"decoded_text": decoded_text}),
        ) from exc
