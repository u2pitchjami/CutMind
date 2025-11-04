from __future__ import annotations

from datetime import datetime
import json
from math import ceil
import os
from pathlib import Path
import shutil
from typing import Any, cast

import cv2
from transformers import PreTrainedModel, ProcessorMixin

from shared.models.config_manager import CONFIG
from shared.utils.config import BATCH_FRAMES_DIR_SC, JSON_STATES_DIR_SC, MULTIPLE_FRAMES_DIR_SC, TMP_FRAMES_DIR_SC
from shared.utils.logger import get_logger
from smartcut.analyze.analyze_torch_utils import (
    estimate_visual_tokens,
    get_model_precision,
    release_gpu_memory,
    vram_gpu,
)
from smartcut.analyze.analyze_utils import (
    delete_frames,
    estimate_safe_batch_size,
    merge_keywords_across_batches,
)
from smartcut.analyze.extract_frames import extract_segment_frames
from smartcut.gen_keywords.load_model import load_qwen_model
from smartcut.gen_keywords.main_gen_keywords import generate_keywords_for_segment
from smartcut.models_sc.ai_result import AIResult
from smartcut.models_sc.smartcut_model import SmartCutSession

logger = get_logger(__name__)
SAFETY_MARGIN: float = CONFIG.smartcut["analyse_segment"]["safety_margin_gb"]

KeywordsBatches = list[AIResult]


# ===========================================================
# 🧠 FONCTION PRINCIPALE : analyse de la vidéo par segments
# ===========================================================
def analyze_by_segments(
    video_path: str,
    session: SmartCutSession,
    frames_per_segment: int = 3,
    auto_frames: bool = True,
    base_rate: int = 5,
    fps_extract: float = 1.0,
    lite: bool = False,
) -> dict[str, list[str]]:
    """
    Extrait des frames pour chaque segment et génère les mots-clés IA.
    Retourne un mapping {segment_uid: keywords}.
    """

    state_path = JSON_STATES_DIR_SC / f"{Path(video_path).stem}.smartcut_state.json"
    logger.debug(f"📥 Démarrage analyze_by_segments : {state_path}")
    frame_data: dict[str, list[str]] = {}

    # Nettoyage répertoires temporaires
    for path in [TMP_FRAMES_DIR_SC, MULTIPLE_FRAMES_DIR_SC, BATCH_FRAMES_DIR_SC]:
        delete_frames(Path(path))
    os.makedirs(TMP_FRAMES_DIR_SC, exist_ok=True)

    if not lite:
        # --- Ouverture vidéo
        video_name = Path(video_path).stem
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.error(f"Impossible d'ouvrir la vidéo {video_path}")
            return {}

    vram_gpu()
    processor, model = load_qwen_model()
    free, _ = vram_gpu()
    precision = get_model_precision(model)
    batch_size = estimate_safe_batch_size(free, precision, SAFETY_MARGIN)
    logger.info(f"🧠 Batch size estimé dynamiquement : {batch_size}")

    # --- 🔁 Boucle principale sur les segments SmartCut
    for seg in session.segments:
        if getattr(seg, "ai_status", "pending") == "done":
            logger.info(f"✅ Segment {seg.id} déjà traité, passage au suivant.")
            continue

        if lite:
            # --- Ouverture vidéo
            if not seg.output_path:
                logger.error(f"Chemin de segment vide pour le segment {seg.id}")
                return {}
            video_name = Path(seg.output_path).stem
            video_path_lite = Path(seg.output_path)
            logger.debug(f"📥 Ouverture vidéo segment lite : {video_name}")
            cap = cv2.VideoCapture(str(video_path_lite))
            if not cap.isOpened():
                logger.error(f"Impossible d'ouvrir la vidéo {video_path_lite}")
                return {}

        start, end = seg.start, seg.end
        logger.info(f"🎬 Analyse segment {seg.id} ({start:.2f}s → {end:.2f}s)")

        frame_paths = extract_segment_frames(cap, video_name, start, end, auto_frames, fps_extract, base_rate)
        if not frame_paths:
            logger.warning(f"Aucune frame extraite pour le segment {seg.id}")
            continue

        keywords_batches = process_batches(
            video_name=video_name,
            start=start,
            end=end,
            frame_paths=frame_paths,
            batch_size=batch_size,
            processor=processor,
            model=model,
        )

        # Fusion des résultats IA
        merged_description, keywords_list = merge_keywords_across_batches(keywords_batches)
        logger.debug(f"🧠 Segment {seg.id} description: {merged_description}")
        logger.debug(f"🧠 Segment {seg.id} keywords: {keywords_list}")

        # --- 💾 Mise à jour du segment
        logger.debug(f"🔍 seg.id={seg.id} mem_id={id(seg)} session_seg_id={id(session.segments[seg.id - 1])}")
        # logger.debug(f"session : {session}")
        seg.description = merged_description
        seg.keywords = keywords_list
        seg.ai_status = "done"
        seg.last_updated = datetime.now().isoformat()
        frame_data[seg.uid] = keywords_list

        session.save(str(state_path))
        logger.debug(f"💾 Session mise à jour (segment {seg.id})")
        # logger.debug(f"session : {session}")

        vram_gpu()

    cap.release()
    release_gpu_memory(model)
    logger.info("✅ Analyse complète terminée.")
    return frame_data


# ===========================================================
# ⚙️ FONCTION DE TRAITEMENT PAR LOTS (batches)
# ===========================================================
def process_batches(
    video_name: str,
    start: float,
    end: float,
    frame_paths: list[str],
    batch_size: int,
    processor: ProcessorMixin,
    model: PreTrainedModel,
) -> KeywordsBatches:
    """
    Traite un segment vidéo par lots et récupère les descriptions + mots-clés IA.
    """

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
        delete_frames(batch_dir)
        release_gpu_memory(model, cache_only=True)

    return all_batches
