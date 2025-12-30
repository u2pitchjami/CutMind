"""
Extraction de mots-clés pour un segment vidéo via Qwen3-VL-4B-Thinking-abliterated (Hugging Face), avec les mêmes
paramètres que le node ComfyUI.
"""

from __future__ import annotations

import os
from pathlib import Path

from qwen_vl_utils import process_vision_info
from transformers import (
    PreTrainedModel,
    ProcessorMixin,
)

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.config import PROMPTS
from shared.utils.settings import get_settings
from smartcut.executors.ia.gen_frames import load_frames_as_tensor, temp_batch_image
from smartcut.executors.ia.parse_output import parse_json_ai_output
from smartcut.models_sc.ai_result import AIOutputType, AIResult

settings = get_settings()

MIN_PIXELS = settings.generate_keywords.min_pixels
MAX_PIXELS = settings.generate_keywords.max_pixels
TOTAL_PIXELS = settings.generate_keywords.total_pixels
SIZEH = settings.generate_keywords.sizeh
SIZEL = settings.generate_keywords.sizel
TOKENIZE = settings.generate_keywords.tokenize
ADD_GENERATION_PROMPT = settings.generate_keywords.add_generation_prompt
PADDING = settings.generate_keywords.padding
RETURN_TENSORS = settings.generate_keywords.return_tensors
MAX_NEW_TOKENS = settings.generate_keywords.max_new_tokens
TEMPERATURE = settings.generate_keywords.temperature
TOP_P = settings.generate_keywords.top_p
REPETITION_PENALTY = settings.generate_keywords.repetition_penalty
DO_SAMPLE = settings.generate_keywords.do_sample
SKIP_SPECIAL_TOKENS = settings.generate_keywords.skip_special_tokens
CLEAN_UP_TOKENIZATION_SPACES = settings.generate_keywords.clean_up_tokenization_spaces


def generate_keywords_from_frames(
    image_path: Path,
    processor: ProcessorMixin,
    model: PreTrainedModel,
    segment_id: str,
    num_frames: int,
    prompt_name: str = "keywords",
    system_prompt: str = "system_keywords",
    output_type: AIOutputType = "full",
) -> AIResult:
    """
    Génération des mots-clés pour un batch de frames.
    """
    SYSTEM_PROMPT = PROMPTS[system_prompt]
    user_prompt = PROMPTS[prompt_name]

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

    try:
        # 1️⃣ Conversion du chat en texte brut pour le modèle
        model_text = processor.apply_chat_template(
            messages, tokenize=TOKENIZE, add_generation_prompt=ADD_GENERATION_PROMPT
        )

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

        decoded_text: str = processor.batch_decode(
            trimmed_ids,
            skip_special_tokens=SKIP_SPECIAL_TOKENS,
            clean_up_tokenization_spaces=CLEAN_UP_TOKENIZATION_SPACES,
        )[0]

        ai_result: AIResult = parse_json_ai_output(decoded_text)

        # Nettoyage du texte
        # if "</think>" in output_text:
        #     output_text = output_text.split("</think>")[-1]

        # output_text = re.sub(r"^[\s\u200b\xa0]+", "", output_text)

        return ai_result
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur lors de la génération des mots clés par IA.",
            code=ErrCode.IAERROR,
            ctx=get_step_ctx({"model": model, "segment_id": segment_id}),
        ) from exc
