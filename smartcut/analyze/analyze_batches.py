from __future__ import annotations

import json
from math import ceil
from pathlib import Path
import shutil
from typing import Any, cast

from transformers import PreTrainedModel, ProcessorMixin

from shared.utils.config import BATCH_FRAMES_DIR_SC
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from smartcut.analyze.analyze_torch_utils import (
    estimate_visual_tokens,
    release_gpu_memory,
)
from smartcut.analyze.analyze_utils import (
    delete_frames,
)
from smartcut.gen_keywords.main_gen_keywords import generate_keywords_for_segment
from smartcut.models_sc.ai_result import AIResult

KeywordsBatches = list[AIResult]


# ===========================================================
# ⚙️ FONCTION DE TRAITEMENT PAR LOTS (batches)
# ===========================================================
@with_child_logger
def process_batches(
    video_name: str,
    start: float,
    end: float,
    frame_paths: list[str],
    batch_size: int,
    processor: ProcessorMixin,
    model: PreTrainedModel,
    logger: LoggerProtocol | None = None,
) -> KeywordsBatches:
    """
    Traite un segment vidéo par lots et récupère les descriptions + mots-clés IA.
    """
    logger = ensure_logger(logger, __name__)
    all_batches: KeywordsBatches = []
    num_batches = ceil(len(frame_paths) / batch_size)

    for b in range(num_batches):
        batch_paths = frame_paths[b * batch_size : (b + 1) * batch_size]
        if not batch_paths:
            continue

        batch_dir = BATCH_FRAMES_DIR_SC / f"{video_name}_seg_{int(start * 10)}_{int(end * 10)}_b{b + 1}"
        batch_dir.mkdir(parents=True, exist_ok=True)

        for src_path in batch_paths:
            dst_path = batch_dir / Path(src_path).name
            try:
                shutil.copy(src_path, dst_path)
            except Exception as e:
                logger.warning(f"⚠️ Erreur de copie {src_path} → {dst_path}: {e}")

        logger.info(f"📦 Batch {b + 1}/{num_batches} → {len(batch_paths)} frames.")
        tokens, limit = estimate_visual_tokens(len(batch_paths))
        logger.info(f"🧮 Contexte : {tokens:,} / {limit:,}")

        batch_result_raw = generate_keywords_for_segment(
            segment_id=f"{video_name}_seg_{int(start * 10)}_{int(end * 10)}",
            frame_dir=batch_dir,
            processor=processor,
            model=model,
            num_frames=len(batch_paths),
            logger=logger,
        )

        parsed_result: AIResult = {"description": "", "keywords": []}

        try:
            if isinstance(batch_result_raw, str):
                parsed = json.loads(batch_result_raw)
                if isinstance(parsed, dict):
                    # normaliser les clés
                    lower = {k.lower(): v for k, v in parsed.items()}
                    parsed_result["description"] = str(lower.get("description", ""))
                    parsed_result["keywords"] = list(lower.get("keywords", []))
                else:
                    parsed_result["keywords"] = [kw.strip() for kw in str(parsed).split(",") if kw.strip()]

            elif isinstance(batch_result_raw, dict):
                lower2: dict[str, Any] = {k.lower(): v for k, v in batch_result_raw.items()}
                parsed_result["description"] = str(lower2.get("description", ""))
                # ✅ Cast explicite pour que mypy voie bien une liste de str
                raw_keywords = lower2.get("keywords", [])
                if isinstance(raw_keywords, list):
                    parsed_result["keywords"] = [str(kw).strip() for kw in raw_keywords if str(kw).strip()]
                elif isinstance(raw_keywords, str):
                    parsed_result["keywords"] = [kw.strip() for kw in raw_keywords.split(",") if kw.strip()]
                else:
                    parsed_result["keywords"] = []

        except json.JSONDecodeError:
            # ✅ Ici on force le type en str pour mypy
            raw_text = cast(str, batch_result_raw)
            parsed_result["keywords"] = [kw.strip() for kw in raw_text.split(",") if kw.strip()]

        # Log lisible
        logger.debug(f"🧠 Batch {b + 1}/{num_batches} description: {parsed_result['description'][:100]}")
        logger.debug(f"🧠 Batch {b + 1}/{num_batches} keywords: {parsed_result['keywords']}")

        all_batches.append(parsed_result)
        delete_frames(batch_dir, logger=logger)
        release_gpu_memory(model, cache_only=True, logger=logger)

    return all_batches
