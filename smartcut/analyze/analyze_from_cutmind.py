from __future__ import annotations

from pathlib import Path

from cutmind.db.repository import CutMindRepository
from cutmind.models_cm.db_models import Segment
from shared.ffmpeg.ffmpeg_utils import get_duration
from shared.models.timer_manager import Timer
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from shared.utils.safe_segments import safe_segments
from smartcut.analyze.analyze_batches import process_batches
from smartcut.analyze.analyze_torch_utils import (
    release_gpu_memory,
)
from smartcut.analyze.analyze_utils import (
    merge_keywords_across_batches,
)
from smartcut.analyze.extract_frames import extract_segment_frames
from smartcut.analyze.prep_analyze import cleanup_temp, open_vid, release_cap
from smartcut.gen_keywords.load_model import load_and_batches


# ===========================================================
# 🧠 FONCTION PRINCIPALE : analyse de la vidéo par segments
# ===========================================================
@safe_segments
@with_child_logger
def analyze_from_cutmind(
    seg: Segment,
    frames_per_segment: int = 3,
    auto_frames: bool = True,
    base_rate: int = 5,
    fps_extract: float = 1.0,
    logger: LoggerProtocol | None = None,
) -> tuple[str, list[str]]:
    """
    Extrait des frames pour chaque segment et génère les mots-clés IA.
    Retourne un mapping {segment_uid: keywords}.
    """
    logger = ensure_logger(logger, __name__)
    repo = CutMindRepository()
    # Nettoyage répertoires temporaires
    cleanup_temp(logger=logger)

    if not seg.output_path:
        raise
    cap, video_name = open_vid(seg.output_path, logger=logger)

    processor, model, model_name, batch_size = load_and_batches(logger=logger)

    start: float = 0.0
    if seg.duration is None:
        end: float = get_duration(Path(seg.output_path), logger=logger)
    else:
        end = seg.duration

    logger.info(f"🎬 Analyse segment {seg.id} ({start:.2f}s → {end:.2f}s)")

    frame_paths = extract_segment_frames(
        cap, video_name, start, end, auto_frames, fps_extract, base_rate, logger=logger
    )
    if not frame_paths:
        logger.warning(f"Aucune frame extraite pour le segment {seg.id}")
        raise
    with Timer(f"Traitement Keywords : {seg.id}", logger):
        keywords_batches = process_batches(
            video_name=video_name,
            start=start,
            end=end,
            frame_paths=frame_paths,
            batch_size=batch_size,
            processor=processor,
            model=model,
            logger=logger,
        )
    # Fusion des résultats IA
    merged_description, keywords_list = merge_keywords_across_batches(keywords_batches, logger=logger)
    logger.debug(f"🧠 Segment {seg.id} description: {merged_description}")
    logger.debug(f"🧠 Segment {seg.id} keywords: {keywords_list}")

    # --- 💾 Mise à jour du segment
    logger.debug(f"🔍 seg.id={seg.id} mem_id={id(seg)}")

    seg.description = merged_description
    seg.keywords = keywords_list
    seg.ai_model = model_name
    repo.update_segment_validation(seg, logger=logger)
    if not seg.id:
        raise
    repo.insert_keywords_standalone(segment_id=seg.id, keywords=seg.keywords, logger=logger)

    logger.debug(f"💾 Session mise à jour (segment {seg.id})")
    # logger.debug(f"session : {session}")

    release_cap(cap)
    release_gpu_memory(model, logger=logger)
    logger.info("✅ Analyse complète terminée.")
    return seg.description, seg.keywords
