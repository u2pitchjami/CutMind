from __future__ import annotations

from typing import Any

import requests

from comfyui_router.utils.logger import get_logger

logger = get_logger("Comfyui Router")


def run_comfy(workflow: dict[str, Any]) -> bool:
    """Envoie un workflow complet à ComfyUI."""
    payload = {"prompt": workflow}

    logger.info("==== JSON ENVOYÉ À COMFYUI ====")
    # ⚠️ Supposons que `workflow` est ton dict JSON après remplacement des chemins vidéo
    # On filtre les nodes invalides (ex: commentaires, nodes UI)

    # On encapsule dans une clé 'prompt' pour respecter l'API ComfyUI

    # Envoi à l’API ComfyUI
    try:
        response = requests.post("http://192.168.50.12:8188/prompt", json=payload, timeout=60)
        response.raise_for_status()
        # logger.debug(response)
        return True
    except requests.HTTPError as e:
        logger.error(f"❌ Erreur HTTP : {e}")
        logger.error("📥 Réponse brute :", response.text)
        return False
