""" """

from __future__ import annotations

import os
import time

import torch
from torch import dtype as TorchDType
from transformers import (
    AutoProcessor,
    BitsAndBytesConfig,
    PreTrainedModel,
    ProcessorMixin,
    Qwen3VLForConditionalGeneration,
)

from cutmind.executors.analyze.analyze_torch_utils import (
    get_model_precision,
    vram_gpu,
)
from cutmind.executors.analyze.analyze_utils import (
    estimate_safe_batch_size,
)
from shared.models.exceptions import CutMindError, ErrCode
from shared.utils.logger import LoggerProtocol, ensure_logger
from shared.utils.settings import get_settings


def resolve_dtype(dtype_str: str) -> TorchDType:
    """
    Convertit une chaîne YAML en type torch.dtype.
    """
    mapping = {
        "torch.float16": torch.float16,
        "torch.float32": torch.float32,
        "torch.bfloat16": torch.bfloat16,
    }
    return mapping.get(dtype_str, torch.float16)


def load_qwen_model(
    force_reload: bool = False, free_vram: float = 0.00, logger: LoggerProtocol | None = None
) -> tuple[ProcessorMixin, PreTrainedModel, str]:
    """
    Charge dynamiquement le modèle Qwen3-VL (4B ou 8B) en fonction de la VRAM disponible.

    Gère automatiquement la quantization via BitsAndBytesConfig uniquement si activée.
    """
    logger = ensure_logger(logger, __name__)
    settings = get_settings()

    FREE_VRAM_8B = settings.generate_keywords.free_vram_8b
    FREE_VRAM_4B = settings.generate_keywords.free_vram_4b
    LOAD_IN_4BIT = settings.generate_keywords.load_in_4bit
    BNB_4BIT_USE_DOUBLE_QUANT = settings.generate_keywords.bnb_4bit_use_double_quant
    BNB_4BIT_QUANT_TYPE = settings.generate_keywords.bnb_4bit_quant_type
    BNB_4BIT_COMPUTE_DTYPE = resolve_dtype(settings.generate_keywords.bnb_4bit_compute_dtype)
    MODEL_4B = settings.generate_keywords.model_4b
    MODEL_8B = settings.generate_keywords.model_8b
    TORCH_DTYPE = settings.generate_keywords.torch_dtype
    DEVICE_MAP = settings.generate_keywords.device_map
    LOAD_IN_4BIT_4B = settings.generate_keywords.load_in_4bit_4b
    BNB_4BIT_USE_DOUBLE_QUANT_4B = settings.generate_keywords.bnb_4bit_use_double_quant_4b
    BNB_4BIT_QUANT_TYPE_4B = settings.generate_keywords.bnb_4bit_quant_type_4b
    BNB_4BIT_COMPUTE_DTYPE_4B = resolve_dtype(settings.generate_keywords.bnb_4bit_compute_dtype_4b)
    DEVICE_MAP_CPU = settings.generate_keywords.device_map_cpu
    ATTN_IMPLEMENTATION = settings.generate_keywords.attn_implementation
    logger.warning("🚀 Loading model in PID: %s", os.getpid())

    # global _MODEL_CACHE, _PROCESSOR_CACHE, _MODEL_NAME_CACHE
    try:
        model_name = None
        quant_config = None

        # --- Sélection du modèle selon la VRAM --- #
        if free_vram >= FREE_VRAM_8B:
            model_name = MODEL_8B

            if LOAD_IN_4BIT:
                quant_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_use_double_quant=BNB_4BIT_USE_DOUBLE_QUANT,
                    bnb_4bit_quant_type=BNB_4BIT_QUANT_TYPE,
                    bnb_4bit_compute_dtype=BNB_4BIT_COMPUTE_DTYPE,
                )
            else:
                quant_config = None

        elif free_vram >= FREE_VRAM_4B:
            model_name = MODEL_4B

            if LOAD_IN_4BIT_4B:
                quant_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_use_double_quant=BNB_4BIT_USE_DOUBLE_QUANT_4B,
                    bnb_4bit_quant_type=BNB_4BIT_QUANT_TYPE_4B,
                    bnb_4bit_compute_dtype=BNB_4BIT_COMPUTE_DTYPE_4B,
                )
            else:
                quant_config = None

        else:
            model_name = MODEL_4B
            quant_config = None
        logger.debug(f"📍 Model  : {model_name}")
        logger.debug(f"📍 quant_config  : {quant_config}")
        logger.warning("🚀 Loading model in PID: %s", os.getpid())
        # --- Chargement du modèle --- #
        model: PreTrainedModel = Qwen3VLForConditionalGeneration.from_pretrained(
            model_name,
            torch_dtype=TORCH_DTYPE,
            device_map=DEVICE_MAP if torch.cuda.is_available() else DEVICE_MAP_CPU,
            attn_implementation=ATTN_IMPLEMENTATION,
            quantization_config=quant_config,  # ← None si non quantisé
        )
        logger.debug(f"📍 model_name   : {model_name}")
        logger.debug(f"📍 torch_dtype   : {TORCH_DTYPE}")
        logger.debug(f"📍 device_map    :  {DEVICE_MAP if torch.cuda.is_available() else DEVICE_MAP_CPU}")
        logger.debug(f"📍 attn_implementation    :  {ATTN_IMPLEMENTATION}")
        logger.debug(f"📍 quantization_config    :  {quant_config}")
        logger.warning("🚀 Loading model in PID: %s", os.getpid())

        processor: ProcessorMixin = AutoProcessor.from_pretrained(model_name)
        model.eval()

        # --- Debug allocations --- #
        # first_param = next(model.parameters())
        # logger.debug(f"📍 Device : {first_param.device}")
        # logger.debug(f"📍 Dtype : {first_param.dtype}")

        return processor, model, model_name

    except Exception as exc:
        raise CutMindError(
            "💥 Erreur lors du chargement du modèle Qwen.",
            code=ErrCode.UNEXPECTED,
            ctx={"step": "load_qwen_model"},
            original_exception=exc,
        ) from exc


def load_and_batches(
    free_gb: float = 0.00, logger: LoggerProtocol | None = None
) -> tuple[ProcessorMixin, PreTrainedModel, str, int, str]:
    """
    lance le modèle et définit la taille du batches
    """
    logger = ensure_logger(logger, __name__)
    settings = get_settings()
    SAFETY_MARGIN = settings.analyse_segment.safety_margin_gb
    logger.debug(f"💡 SSAFETY_MARGIN {SAFETY_MARGIN}")
    logger.debug(f"💡 free_gb {free_gb}")
    try:
        processor, model, model_name = load_qwen_model(free_vram=free_gb, logger=logger)
        # 🔥 Stabilisation mémoire GPU
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            time.sleep(10)
        free_gb, total_gb = vram_gpu()
        precision = get_model_precision(model)
        batch_size = estimate_safe_batch_size(free_gb, total_gb, precision, SAFETY_MARGIN)
    except Exception as exc:
        raise CutMindError(
            "❌ Impossible d'ouvrir la vidéo.",
            code=ErrCode.UNEXPECTED,
            ctx={"step": "load_and_batches", "free_gb": free_gb},
            original_exception=exc,
        ) from exc
    return processor, model, model_name, batch_size, precision
