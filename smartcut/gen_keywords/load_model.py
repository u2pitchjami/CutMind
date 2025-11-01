""" """

from __future__ import annotations

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

from shared.models.config_manager import CONFIG
from shared.utils.logger import get_logger
from smartcut.gen_keywords.gen_utils import get_free_vram_gb

logger = get_logger(__name__)


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


FREE_VRAM_8B = CONFIG.smartcut["generate_keywords"]["free_vram_8b"]
FREE_VRAM_4B = CONFIG.smartcut["generate_keywords"]["free_vram_4b"]
LOAD_IN_4BIT = CONFIG.smartcut["generate_keywords"]["load_in_4bit"]
BNB_4BIT_USE_DOUBLE_QUANT = CONFIG.smartcut["generate_keywords"]["bnb_4bit_use_double_quant"]
BNB_4BIT_QUANT_TYPE = CONFIG.smartcut["generate_keywords"]["bnb_4bit_quant_type"]
BNB_4BIT_COMPUTE_DTYPE = resolve_dtype(CONFIG.smartcut["generate_keywords"]["bnb_4bit_compute_dtype"])
LOAD_IN_4BIT_4B = CONFIG.smartcut["generate_keywords"]["load_in_4bit_4b"]
BNB_4BIT_USE_DOUBLE_QUANT_4B = CONFIG.smartcut["generate_keywords"]["bnb_4bit_use_double_quant_4b"]
BNB_4BIT_QUANT_TYPE_4B = CONFIG.smartcut["generate_keywords"]["bnb_4bit_quant_type_4b"]
BNB_4BIT_COMPUTE_DTYPE_4B = resolve_dtype(CONFIG.smartcut["generate_keywords"]["bnb_4bit_compute_dtype_4b"])
MODEL_4B = CONFIG.smartcut["generate_keywords"]["model_4b"]
MODEL_8B = CONFIG.smartcut["generate_keywords"]["model_8b"]
TORCH_DTYPE = CONFIG.smartcut["generate_keywords"]["torch_dtype"]
DEVICE_MAP = CONFIG.smartcut["generate_keywords"]["device_map"]
DEVICE_MAP_CPU = CONFIG.smartcut["generate_keywords"]["device_map_cpu"]
ATTN_IMPLEMENTATION = CONFIG.smartcut["generate_keywords"]["attn_implementation"]


def load_qwen_model(force_reload: bool = False) -> tuple[ProcessorMixin, PreTrainedModel]:
    """
    Charge dynamiquement le modèle Qwen3-VL (4B ou 8B) en fonction de la VRAM disponible.

    Gère automatiquement la quantization via BitsAndBytesConfig uniquement si activée.
    """

    global _MODEL_CACHE, _PROCESSOR_CACHE, _MODEL_NAME_CACHE
    try:
        free_vram = get_free_vram_gb()
        logger.info(f"💾 VRAM libre détectée : {free_vram:.2f} Go")

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
                logger.info("🚀 Chargement du modèle Qwen 8B (quantized 4-bit)")
            else:
                quant_config = None
                logger.info("🚀 Chargement du modèle Qwen 8B (full precision)")

        elif free_vram >= FREE_VRAM_4B:
            model_name = MODEL_4B

            if LOAD_IN_4BIT_4B:
                quant_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_use_double_quant=BNB_4BIT_USE_DOUBLE_QUANT_4B,
                    bnb_4bit_quant_type=BNB_4BIT_QUANT_TYPE_4B,
                    bnb_4bit_compute_dtype=BNB_4BIT_COMPUTE_DTYPE_4B,
                )
                logger.info("🚀 Chargement du modèle Qwen 4B (quantized 4-bit)")
            else:
                quant_config = None
                logger.info("🚀 Chargement du modèle Qwen 4B (full precision)")

        else:
            logger.warning("⚠️ VRAM insuffisante, passage en mode CPU (très lent)")
            model_name = MODEL_4B
            quant_config = None

        # --- Chargement du modèle --- #
        start = time.time()
        model: PreTrainedModel = Qwen3VLForConditionalGeneration.from_pretrained(
            model_name,
            torch_dtype=TORCH_DTYPE,
            device_map=DEVICE_MAP if torch.cuda.is_available() else DEVICE_MAP_CPU,
            attn_implementation=ATTN_IMPLEMENTATION,
            quantization_config=quant_config,  # ← None si non quantisé
        )

        processor: ProcessorMixin = AutoProcessor.from_pretrained(model_name)
        model.eval()

        elapsed = time.time() - start
        logger.info(f"✅ Modèle {model_name} chargé en {elapsed:.1f}s")
        logger.info(f"📊 VRAM après chargement : {get_free_vram_gb():.2f} Go libres")

        # --- Debug allocations --- #
        try:
            first_param = next(model.parameters())
            logger.debug(f"📍 Device : {first_param.device}")
            logger.debug(f"📍 Dtype : {first_param.dtype}")
        except Exception as debug_err:
            logger.warning(f"⚠️ Impossible d'inspecter les paramètres : {debug_err}")

        return processor, model

    except Exception as e:
        logger.error(f"💥 Erreur lors du chargement du modèle Qwen : {e}")
        raise
