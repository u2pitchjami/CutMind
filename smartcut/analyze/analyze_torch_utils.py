""" """

from __future__ import annotations

import gc

import torch
from transformers import (
    PreTrainedModel,
)

from shared.models.config_manager import CONFIG
from shared.utils.logger import get_logger

logger = get_logger(__name__)

LIMIT_TOKENS = CONFIG.smartcut["analyse_segment"]["limit_tokens"]


def get_model_precision(model: torch.nn.Module) -> str:
    """
    Détecte automatiquement la précision du modèle (4bit ou floatX).
    """
    for module in model.modules():
        class_name = module.__class__.__name__.lower()
        if "4bit" in class_name or "bnb" in class_name:
            return "4bit"
    try:
        dtype = next(model.parameters()).dtype
        if dtype == torch.float32:
            return "float32"
        elif dtype == torch.float16:
            return "float16"
        elif dtype == torch.bfloat16:
            return "bfloat16"
    except Exception:
        pass
    return "unknown"


def vram_gpu() -> tuple[float, float]:
    """
    Retourne la (VRAM libre, VRAM totale) en Go et logge l'état.
    """
    free_bytes, total_bytes = torch.cuda.mem_get_info()
    free_gb = free_bytes / 1e9
    total_gb = total_bytes / 1e9
    logger.info(f"VRAM libre: {free_gb:.2f} Go / {total_gb:.2f} Go")
    return free_gb, total_gb


def release_gpu_memory(model: PreTrainedModel = None, cache_only: bool = True) -> None:
    """
    Libère la mémoire GPU :

    - Si cache_only=True : ne décharge pas le modèle, vide uniquement le cache et les tensors temporaires
    - Si cache_only=False : décharge aussi le modèle de la VRAM
    """
    if not cache_only and model is not None:
        del model

    gc.collect()
    torch.cuda.empty_cache()
    torch.cuda.synchronize()

    free, total = torch.cuda.mem_get_info()
    logger.info(
        f"🧹 VRAM nettoyée ({'cache_only' if cache_only else 'full release'}) → "
        f"VRAM libre : {free / 1e9:.2f} Go / {total / 1e9:.2f} Go"
    )


def estimate_visual_tokens(num_images: int, model_name: str = "qwen3-vl-instruct-4b") -> tuple[int, int]:
    """
    Estime le nombre total de tokens (texte + images) et la limite max du modèle.
    """
    tokens = num_images * 400 + 500  # 400 tokens/image + marge texte
    # Qwen3-VL-4B-Instruct-abliterated → 262144 tokens
    limit = LIMIT_TOKENS
    return tokens, limit
