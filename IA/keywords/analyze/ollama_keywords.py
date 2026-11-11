"""Analyse des frames via un serveur Ollama, sans charger de modèle HF."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from io import BytesIO
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
import time
from typing import Any

from PIL import Image
import requests

from IA.keywords.utils.ai_result import AIOutputType, AIResult
from IA.keywords.utils.parse_output import parse_json_ai_output
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.config import PROMPTS
from shared.utils.logger import LoggerProtocol, ensure_logger
from shared.utils.settings import get_settings


def output_schema(output_type: AIOutputType) -> dict[str, Any]:
    if output_type == AIOutputType.SCENE_ANALYSIS:
        properties = {
            "description": {"type": "string"},
            "category": {"type": ["string", "null"]},
            "keywords": {"type": "array", "items": {"type": "string"}},
        }
    elif output_type == AIOutputType.SCENE_RATING:
        properties = {
            "quality_rating": {"type": "number", "minimum": 1, "maximum": 5},
            "interest_rating": {"type": "number", "minimum": 1, "maximum": 10},
        }
    else:
        raise ValueError(f"Type de sortie IA inconnu : {output_type}")
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def save_truncated_response(data: dict[str, Any], metadata: dict[str, Any], logger: LoggerProtocol) -> Path | None:
    """Conserver la sortie textuelle complète, sans images ni contenu de raisonnement."""
    try:
        directory = Path("/app/logs/cutmind")
        directory.mkdir(parents=True, exist_ok=True)
        message = data.get("message")
        diagnostic = {
            "created_at": datetime.now(UTC).isoformat(),
            **metadata,
            "response": {
                key: data.get(key)
                for key in (
                    "model",
                    "done",
                    "done_reason",
                    "prompt_eval_count",
                    "eval_count",
                    "total_duration",
                    "load_duration",
                    "prompt_eval_duration",
                    "eval_duration",
                )
            },
            "content": message.get("content") if isinstance(message, dict) else None,
            "has_thinking": isinstance(message, dict) and bool(message.get("thinking")),
        }
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=directory,
            prefix=datetime.now(UTC).strftime("truncated_%Y%m%dT%H%M%S_"),
            suffix=".json",
            delete=False,
        ) as diagnostic_file:
            path = Path(diagnostic_file.name)
            json.dump(diagnostic, diagnostic_file, ensure_ascii=False, indent=2)
            diagnostic_file.write("\n")
        logger.warning("Réponse Ollama tronquée sauvegardée : %s", path)
        return path
    except (OSError, TypeError, ValueError) as exc:
        logger.warning("Impossible de sauvegarder le diagnostic Ollama : %s", exc)
        return None


def generate_keywords_with_ollama(
    frame_dir: Path,
    segment_id: str,
    num_frames: int,
    output_type: AIOutputType,
    prompt_name: str = "keywords",
    system_prompt: str = "system_keywords",
    logger: LoggerProtocol | None = None,
) -> AIResult:
    logger = ensure_logger(logger, __name__)
    settings = get_settings().generate_keywords
    context = {"backend": "ollama", "model": settings.ollama_model, "segment_id": segment_id}
    try:
        paths = sorted(frame_dir.glob(f"{segment_id}_*.jpg"))[:num_frames] if num_frames > 0 else []
        if not paths:
            raise CutMindError("Aucune frame pour le segment en cours.", code=ErrCode.NOFILE)

        images: list[str] = []
        for path in paths:
            with Image.open(path) as source:
                # Même taille et encodage JPEG que le chemin Transformers.
                image = source.convert("RGB").resize((settings.sizeh, settings.sizel))
                buffer = BytesIO()
                image.save(buffer, format="JPEG", quality=95)
                images.append(base64.b64encode(buffer.getvalue()).decode("ascii"))

        payload = {
            "model": settings.ollama_model,
            "messages": [
                {"role": "system", "content": PROMPTS[system_prompt]},
                {"role": "user", "content": PROMPTS[prompt_name], "images": images},
            ],
            "stream": False,
            "think": settings.ollama_think,
            "format": output_schema(output_type),
            "keep_alive": settings.ollama_keep_alive,
            "options": {
                "num_ctx": settings.ollama_num_ctx,
                "num_predict": settings.max_new_tokens,
                "temperature": settings.temperature if settings.do_sample else 0,
                "top_p": settings.top_p,
                "repeat_penalty": settings.repetition_penalty,
            },
        }
        started = time.monotonic()
        with requests.post(
            f"{settings.ollama_base_url}/api/chat",
            json=payload,
            timeout=(10, settings.ollama_timeout),
        ) as response:
            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                detail = ""
                try:
                    error_data = response.json()
                    if isinstance(error_data, dict) and isinstance(error_data.get("error"), str):
                        detail = error_data["error"][:1000]
                except ValueError:
                    pass
                raise CutMindError(
                    f"Ollama HTTP {response.status_code} : {detail or 'erreur sans détail JSON'}",
                    code=ErrCode.IAERROR,
                    ctx={**context, "status": response.status_code},
                ) from exc
            data = response.json()

        if not isinstance(data, dict):
            raise ValueError("La réponse Ollama n'est pas un objet JSON.")
        message = data.get("message")
        logger.debug(
            "Ollama réponse batch segment=%s prompt=%s modèle=%s done=%s raison=%s content=%s",
            segment_id,
            prompt_name,
            settings.ollama_model,
            data.get("done"),
            data.get("done_reason"),
            message.get("content") if isinstance(message, dict) else None,
        )
        if data.get("error"):
            raise ValueError(f"Erreur retournée par Ollama : {data['error']}")
        if data.get("done") is not True or data.get("done_reason") == "length":
            message = data.get("message")
            has_thinking = isinstance(message, dict) and bool(message.get("thinking"))
            diagnostic_path = save_truncated_response(
                data,
                {
                    **context,
                    "prompt_name": prompt_name,
                    "system_prompt_name": system_prompt,
                    "output_type": output_type.value,
                    "image_count": len(images),
                    "options": payload["options"],
                    "think": settings.ollama_think,
                },
                logger,
            )
            if diagnostic_path is not None:
                context["diagnostic_path"] = str(diagnostic_path)
            diagnostic_hint = (
                f"Diagnostic : {diagnostic_path}."
                if diagnostic_path is not None
                else "Diagnostic non sauvegardé (voir les logs)."
            )
            raise ValueError(
                "Réponse Ollama incomplète ou limite de tokens atteinte "
                f"(done={data.get('done')}, raison={data.get('done_reason')}, "
                f"tokens générés={data.get('eval_count')}, limite={settings.max_new_tokens}, "
                f"contexte={settings.ollama_num_ctx}, think={settings.ollama_think}, "
                f"raisonnement présent={has_thinking}). "
                f"{diagnostic_hint} Examiner la sortie avant de modifier generate_keywords.max_new_tokens."
            )
        message = data.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Réponse Ollama vide ou sans message.content.")
        result = parse_json_ai_output(content, output_type)
        required = output_schema(output_type)["required"]
        if any(key not in result or (key != "category" and result.get(key) is None) for key in required):
            raise ValueError("Réponse Ollama ne contenant pas tous les champs attendus.")
        logger.info(
            "Ollama modèle=%s images=%d durée=%.2fs tokens entrée=%s sortie=%s",
            settings.ollama_model,
            len(images),
            time.monotonic() - started,
            data.get("prompt_eval_count"),
            data.get("eval_count"),
        )
        return result
    except CutMindError as exc:
        raise exc.with_context(get_step_ctx(context)) from exc
    except requests.Timeout as exc:
        raise CutMindError("Délai d'attente Ollama dépassé.", code=ErrCode.IAERROR, ctx=context) from exc
    except requests.ConnectionError as exc:
        raise CutMindError("Connexion au serveur Ollama impossible.", code=ErrCode.IAERROR, ctx=context) from exc
    except Exception as exc:
        raise CutMindError(
            f"Erreur lors de l'analyse Ollama : {exc}",
            code=ErrCode.IAERROR,
            ctx=context,
        ) from exc
