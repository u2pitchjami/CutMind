""" """

from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.config import HOST_ROOT, VISIBLE_ROOT


def comfyui_path(full_path: Path) -> Path:
    try:
        host_root = Path(HOST_ROOT)
        visible_root = Path(VISIBLE_ROOT)
        return visible_root / full_path.relative_to(host_root)
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors de la construction du path Comfyui.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx(),
        ) from exc


def run_comfy(workflow: dict[str, Any]) -> bool:
    """
    Envoie un workflow complet à ComfyUI.
    """
    payload = {"prompt": workflow}

    # ⚠️ Supposons que `workflow` est ton dict JSON après remplacement des chemins vidéo
    # On filtre les nodes invalides (ex: commentaires, nodes UI)

    # On encapsule dans une clé 'prompt' pour respecter l'API ComfyUI

    # Envoi à l’API ComfyUI
    try:
        response = requests.post("http://192.168.50.12:8188/prompt", json=payload, timeout=60)
        response.raise_for_status()
        return True
    except requests.HTTPError as err:
        raise CutMindError(
            "❌ Erreur inattendue lors de l'envoie du worflow à Comfyui.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"Réponse brute": response.text}),
        ) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors de l'envoie du worflow à Comfyui.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx(),
        ) from exc
