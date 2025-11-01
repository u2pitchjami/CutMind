"""
Extraction de mots-clés pour un segment vidéo via Qwen3-VL-4B-Thinking-abliterated (Hugging Face), avec les mêmes
paramètres que le node ComfyUI.
"""

from __future__ import annotations

import os
from pathlib import Path
import re

from qwen_vl_utils import process_vision_info
from transformers import (
    PreTrainedModel,
    ProcessorMixin,
)

from shared.models.config_manager import CONFIG
from shared.utils.config import PROMPTS
from shared.utils.logger import get_logger
from smartcut.gen_keywords.gen_frames import load_frames_as_tensor, temp_batch_image

logger = get_logger(__name__)

MAX_NEW_TOKENS = CONFIG.smartcut["generate_keywords"]["max_new_tokens"]
MIN_PIXELS = CONFIG.smartcut["generate_keywords"]["min_pixels"]
MAX_PIXELS = CONFIG.smartcut["generate_keywords"]["max_pixels"]
TOTAL_PIXELS = CONFIG.smartcut["generate_keywords"]["total_pixels"]
SIZEH = CONFIG.smartcut["generate_keywords"]["sizeh"]
SIZEL = CONFIG.smartcut["generate_keywords"]["sizel"]

TOKENIZE = CONFIG.smartcut["generate_keywords"]["tokenize"]
ADD_GENERATION_PROMPT = CONFIG.smartcut["generate_keywords"]["add_generation_prompt"]

PADDING = CONFIG.smartcut["generate_keywords"]["padding"]
RETURN_TENSORS = CONFIG.smartcut["generate_keywords"]["return_tensors"]

TEMPERATURE = CONFIG.smartcut["generate_keywords"]["temperature"]
TOP_P = CONFIG.smartcut["generate_keywords"]["top_p"]
REPETITION_PENALTY = CONFIG.smartcut["generate_keywords"]["repetition_penalty"]
DO_SAMPLE = CONFIG.smartcut["generate_keywords"]["do_sample"]

SKIP_SPECIAL_TOKENS = CONFIG.smartcut["generate_keywords"]["skip_special_tokens"]
CLEAN_UP_TOKENIZATION_SPACES = CONFIG.smartcut["generate_keywords"]["clean_up_tokenization_spaces"]


def generate_keywords_from_frames(
    image_path: Path,
    processor: ProcessorMixin,
    model: PreTrainedModel,
    segment_id: str,
    num_frames: int,
) -> str:
    """
    Génération des mots-clés pour un batch de frames.
    """

    SYSTEM_PROMPT = PROMPTS["system_keywords"]
    user_prompt = PROMPTS["keywords"]

    content = []

    # Paramètres visuels équivalents à ComfyUI
    min_pixels = MIN_PIXELS * 28 * 28
    max_pixels = MAX_PIXELS * 28 * 28
    total_pixels = TOTAL_PIXELS * 28 * 28

    frames_tensor = load_frames_as_tensor(
        frames_dir=image_path,
        segment_id=segment_id,
        size=(SIZEH, SIZEL),
        max_frames=num_frames,
    )

    image_paths = temp_batch_image(frames_tensor, seed=segment_id)
    content = [
        *[
            {
                "type": "image",
                "image": path,
                "min_pixels": min_pixels,
                "max_pixels": max_pixels,
                "total_pixels": total_pixels,
            }
            for path in image_paths
        ],
        {"type": "text", "text": user_prompt},
    ]

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]

    # 1️⃣ Conversion du chat en texte brut pour le modèle
    model_text = processor.apply_chat_template(messages, tokenize=TOKENIZE, add_generation_prompt=ADD_GENERATION_PROMPT)

    os.environ["FORCE_QWENVL_VIDEO_READER"] = "torchvision"

    # 2️⃣ Préparation des entrées visuelles
    image_inputs, video_inputs, video_kwargs = process_vision_info(messages, return_video_kwargs=True)

    # 3️⃣ Construction finale des inputs tensors
    inputs = processor(
        text=[model_text],
        images=image_inputs,
        videos=video_inputs,
        padding=PADDING,
        return_tensors=RETURN_TENSORS,
        **video_kwargs,
    ).to(model.device)

    logger.debug("🧩 Entrées préparées, génération en cours pour %s", image_path.name)

    # Génération identique à ComfyUI
    generated_ids = model.generate(
        **inputs,
        max_new_tokens=MAX_NEW_TOKENS,
        temperature=TEMPERATURE,
        top_p=TOP_P,
        repetition_penalty=REPETITION_PENALTY,
        do_sample=DO_SAMPLE,
        eos_token_id=processor.tokenizer.eos_token_id,
        pad_token_id=processor.tokenizer.pad_token_id,
    )

    # Retrait du prompt d'entrée (comme dans le node)
    trimmed_ids = [out_ids[len(in_ids) :] for in_ids, out_ids in zip(inputs.input_ids, generated_ids, strict=False)]

    output_text: str = processor.batch_decode(
        trimmed_ids,
        skip_special_tokens=SKIP_SPECIAL_TOKENS,
        clean_up_tokenization_spaces=CLEAN_UP_TOKENIZATION_SPACES,
    )[0]

    # Nettoyage du texte
    if "</think>" in output_text:
        output_text = output_text.split("</think>")[-1]

    output_text = re.sub(r"^[\s\u200b\xa0]+", "", output_text)

    logger.info("🔑 Mots-clés générés pour %s : %s", image_path.name, output_text)
    return output_text
