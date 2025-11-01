""" """

from __future__ import annotations

from datetime import datetime
from math import ceil
import os
from pathlib import Path
import shutil

import cv2
from transformers import (
    PreTrainedModel,
    ProcessorMixin,
)

from shared.models.config_manager import CONFIG
from shared.models.smartcut_model import SmartCutSession
from shared.utils.config import BATCH_FRAMES_DIR_SC, MULTIPLE_FRAMES_DIR_SC, TMP_FRAMES_DIR_SC
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

logger = get_logger(__name__)

SAFETY_MARGIN = CONFIG.smartcut["analyse_segment"]["safety_margin_gb"]


def analyze_by_segments(
    video_path: str,
    session: SmartCutSession,
    frames_per_segment: int = 3,
    auto_frames: bool = True,
    base_rate: int = 5,
    fps_extract: float = 1.0,
) -> dict[str, list[str]]:
    """
    Extrait des frames pour chaque segment de la session et génère les mots-clés IA.

    - Utilise directement les objets Segment (plus de tuples start/end)
    - Met à jour la session en mémoire (keywords, ai_status, last_updated)
    - Sauvegarde le JSON de session après chaque segment traité
    """
    logger.debug("📥 Démarrage analyze_by_segments")
    frame_data: dict[str, list[str]] = {}
    video_name = Path(video_path).stem

    # Nettoyage des répertoires temporaires
    for path in [TMP_FRAMES_DIR_SC, MULTIPLE_FRAMES_DIR_SC, BATCH_FRAMES_DIR_SC]:
        delete_frames(Path(path))
    os.makedirs(TMP_FRAMES_DIR_SC, exist_ok=True)

    # Initialisation vidéo et modèle IA
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

    # --- 🔁 Boucle principale sur les segments SmartCut ---
    for seg in session.segments:
        start, end = seg.start, seg.end
        logger.info(f"🎬 Analyse segment {seg.id} ({start:.2f}s → {end:.2f}s)")

        frame_paths = extract_segment_frames(cap, video_name, start, end, auto_frames, fps_extract, base_rate)
        if not frame_paths:
            logger.warning(f"Aucune frame extraite pour le segment {seg.id}")
            continue

        # IA : génération des mots-clés
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
        merged_keywords = (
            keywords_batches[0] if len(keywords_batches) == 1 else merge_keywords_across_batches(keywords_batches)
        )
        keywords_list = [kw.strip() for kw in merged_keywords.split(",") if kw.strip()]
        logger.debug(f"🧠 Segment {seg.id} keywords: {keywords_list}")

        # --- 💾 Mise à jour du segment ---
        seg.keywords = keywords_list
        seg.ai_status = "done"
        seg.last_updated = datetime.now().isoformat()
        frame_data[seg.uid] = keywords_list

        # Sauvegarde session après chaque segment
        session.save()
        logger.debug(f"💾 Session mise à jour (segment {seg.id})")

        vram_gpu()  # nettoyage VRAM intermédiaire

    cap.release()
    release_gpu_memory(model)

    logger.info("✅ Analyse complète terminée.")
    return frame_data


def process_batches(
    video_name: str,
    start: float,
    end: float,
    frame_paths: list[str],
    batch_size: int,
    processor: ProcessorMixin,
    model: PreTrainedModel,
) -> list[str]:
    keywords_all_batches: list[str] = []
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

        # batch_keywords: str = "truc, bidule, machin"
        batch_keywords = generate_keywords_for_segment(
            segment_id=f"{video_name}_seg_{int(start * 10)}_{int(end * 10)}",
            frame_dir=batch_dir,
            processor=processor,
            model=model,
            num_frames=len(batch_paths),
        )

        if batch_keywords:
            logger.debug(f"batch_keywords : {batch_keywords[:50]}")
            keywords_all_batches.append(batch_keywords)

        delete_frames(batch_dir)
        release_gpu_memory(model, cache_only=True)

    return keywords_all_batches
