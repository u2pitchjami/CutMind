""" """

from __future__ import annotations

import gc
import time

import torch
from transformers import PreTrainedModel, ProcessorMixin

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from shared.utils.settings import get_settings


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


def release_gpu_memory(
    model: PreTrainedModel = None,
    processor: ProcessorMixin = None,
    extra_objects: list[object] | None = None,
    logger: LoggerProtocol | None = None,
    cache_only: bool = True,
) -> None:
    """
    Libère la mémoire GPU :

    - Si cache_only=True : ne décharge pas le modèle, vide uniquement le cache et les tensors temporaires
    - Si cache_only=False : décharge aussi le modèle de la VRAM
    """
    logger = ensure_logger(logger, __name__)
    try:
        if not cache_only:
            for obj in [model, processor] + (extra_objects or []):
                try:
                    del obj
                except Exception:
                    pass
        else:
            for obj in extra_objects or []:
                try:
                    del obj
                except Exception:
                    pass

        gc.collect()
        torch.cuda.empty_cache()
        torch.cuda.synchronize()

        allocated = torch.cuda.memory_allocated() / 1024**2
        reserved = torch.cuda.memory_reserved() / 1024**2
        logger.info(f"🧹 VRAM libérée → Allocated: {allocated:.2f} MB | Reserved: {reserved:.2f} MB")

    except Exception as exc:
        logger.warning(f"⚠️ Erreur libération VRAM : {exc}")


def estimate_visual_tokens(num_images: int, model_name: str = "qwen3-vl-instruct-4b") -> tuple[int, int]:
    """
    Estime le nombre total de tokens (texte + images) et la limite max du modèle.
    """
    settings = get_settings()

    LIMIT_TOKENS = settings.analyse_segment.limit_tokens
    tokens = num_images * 400 + 500  # 400 tokens/image + marge texte
    # Qwen3-VL-4B-Instruct-abliterated → 262144 tokens
    limit = LIMIT_TOKENS
    return tokens, limit


# ============================================================
# 🧹 Outils GPU
# ============================================================
@with_child_logger
def auto_clean_gpu(max_wait_sec: int = 30, logger: LoggerProtocol | None = None) -> None:
    """Nettoie la VRAM GPU et synchronise CUDA."""
    logger = ensure_logger(logger, __name__)
    waited = 0
    while not torch.cuda.is_available():
        if waited >= max_wait_sec:
            logger.warning(f"❌ GPU non détecté après {max_wait_sec}s.")
            return
        logger.info("⏳ En attente du GPU CUDA...")
        time.sleep(2)
        waited += 2

    try:
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
        gc.collect()
        free, total = torch.cuda.mem_get_info()
        logger.info(f"🧹 GPU nettoyé : {free / 1e9:.2f} Go libres / {total / 1e9:.2f} Go totaux")
    except CutMindError as err:
        raise err.with_context(get_step_ctx()) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur lors du Nettoyage VRAM.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx(),
            original_exception=exc,
        ) from exc
