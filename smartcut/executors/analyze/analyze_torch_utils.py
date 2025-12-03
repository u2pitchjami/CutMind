""" """

from __future__ import annotations

import gc

import torch
from transformers import PreTrainedModel

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.settings import get_settings

settings = get_settings()

LIMIT_TOKENS = settings.analyse_segment.limit_tokens


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
    if not torch.cuda.is_available():
        return 0.0, 0.0
    free_bytes, total_bytes = torch.cuda.mem_get_info()
    free_gb = free_bytes / 1e9
    total_gb = total_bytes / 1e9
    return free_gb, total_gb


def release_gpu_memory(model: PreTrainedModel = None, cache_only: bool = True) -> None:
    """
    Libère la mémoire GPU :

    - Si cache_only=True : ne décharge pas le modèle, vide uniquement le cache et les tensors temporaires
    - Si cache_only=False : décharge aussi le modèle de la VRAM
    """
    if not cache_only and model is not None:
        del model
    try:
        gc.collect()
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors de libération de VRAM.",
            code=ErrCode.VIDEO,
            ctx=get_step_ctx({"model": model, "cache_only": cache_only}),
        ) from exc


def estimate_visual_tokens(num_images: int, model_name: str = "qwen3-vl-instruct-4b") -> tuple[int, int]:
    """
    Estime le nombre total de tokens (texte + images) et la limite max du modèle.
    """
    tokens = num_images * 400 + 500  # 400 tokens/image + marge texte
    # Qwen3-VL-4B-Instruct-abliterated → 262144 tokens
    limit = LIMIT_TOKENS
    return tokens, limit
