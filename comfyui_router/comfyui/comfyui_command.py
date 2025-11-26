""" """

from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

from shared.utils.config import HOST_ROOT, VISIBLE_ROOT
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger


def comfyui_path(full_path: Path) -> Path:
    host_root = Path(HOST_ROOT)
    visible_root = Path(VISIBLE_ROOT)
    return visible_root / full_path.relative_to(host_root)


@with_child_logger
def run_comfy(workflow: dict[str, Any], logger: LoggerProtocol | None = None) -> bool:
    """
    Envoie un workflow complet à ComfyUI.
    """
    logger = ensure_logger(logger, __name__)
    payload = {"prompt": workflow}

    logger.info("==== JSON ENVOYÉ À COMFYUI ====")
    # ⚠️ Supposons que `workflow` est ton dict JSON après remplacement des chemins vidéo
    # On filtre les nodes invalides (ex: commentaires, nodes UI)

    # On encapsule dans une clé 'prompt' pour respecter l'API ComfyUI

    # Envoi à l’API ComfyUI
    try:
        response = requests.post("http://192.168.50.12:8188/prompt", json=payload, timeout=60)
        response.raise_for_status()
        return True
    except requests.HTTPError as e:
        logger.error(f"❌ Erreur HTTP : {e}")
        logger.error("📥 Réponse brute :", response.text)
        return False
