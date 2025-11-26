from __future__ import annotations

from datetime import datetime
from pathlib import Path

from shared.models.timer_manager import Timer
from shared.utils.config import JSON_STATES_DIR_SC
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from shared.utils.safe_segments import safe_segments
from smartcut.analyze.analyze_batches import process_batches
from smartcut.analyze.analyze_torch_utils import (
    release_gpu_memory,
    vram_gpu,
)
from smartcut.analyze.analyze_utils import (
    merge_keywords_across_batches,
)
from smartcut.analyze.extract_frames import extract_segment_frames
from smartcut.analyze.prep_analyze import cleanup_temp, open_vid, release_cap
from smartcut.gen_keywords.load_model import load_and_batches
from smartcut.models_sc.smartcut_model import SmartCutSession


# ===========================================================
# 🧠 FONCTION PRINCIPALE : analyse de la vidéo par segments
# ===========================================================
@safe_segments
@with_child_logger
def analyze_by_segments(
    video_path: str,
    session: SmartCutSession,
    frames_per_segment: int = 3,
    auto_frames: bool = True,
    base_rate: int = 5,
    fps_extract: float = 1.0,
    lite: bool = False,
    logger: LoggerProtocol | None = None,
) -> dict[str, list[str]]:
    """
    Extrait des frames pour chaque segment et génère les mots-clés IA.
    Retourne un mapping {segment_uid: keywords}.
    """
    logger = ensure_logger(logger, __name__)
    state_path = JSON_STATES_DIR_SC / f"{Path(video_path).stem}.smartcut_state.json"
    logger.debug(f"📥 Démarrage analyze_by_segments : {state_path}")
    frame_data: dict[str, list[str]] = {}

    # Nettoyage répertoires temporaires
    cleanup_temp(logger=logger)

    if not lite:
        # --- Ouverture vidéo
        cap, video_name = open_vid(video_path, logger=logger)

    processor, model, model_name, batch_size = load_and_batches(logger=logger)

    # --- 🔁 Boucle principale sur les segments SmartCut
    with Timer(f"Traitement Keywords : {session.video_name}", logger):
        for seg in session.segments:
            if getattr(seg, "ai_status", "pending") == "done":
                logger.info(f"✅ Segment {seg.id} déjà traité, passage au suivant.")
                continue

            if lite:
                # --- Ouverture vidéo
                if not seg.output_path:
                    logger.error(f"Chemin de segment vide pour le segment {seg.id}")
                    return {}
                video_path_lite = Path(seg.output_path)
                cap, video_name = open_vid(str(video_path_lite), logger=logger)
                logger.debug(f"📥 Ouverture vidéo segment lite : {video_name}")

            start, end = seg.start, seg.end
            logger.info(f"🎬 Analyse segment {seg.id} ({start:.2f}s → {end:.2f}s)")

            frame_paths = extract_segment_frames(
                cap, video_name, start, end, auto_frames, fps_extract, base_rate, logger=logger
            )
            if not frame_paths:
                logger.warning(f"Aucune frame extraite pour le segment {seg.id}")
                continue

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
            logger.debug(f"🔍 seg.id={seg.id} mem_id={id(seg)} session_seg_id={id(session.segments[seg.id - 1])}")
            # logger.debug(f"session : {session}")
            seg.description = merged_description
            seg.keywords = keywords_list
            seg.ai_status = "done"
            seg.status = "ia_done"
            seg.ai_model = model_name
            seg.last_updated = datetime.now().isoformat()
            frame_data[seg.uid] = keywords_list

            session.save(str(state_path))
            logger.debug(f"💾 Session mise à jour (segment {seg.id})")
            # logger.debug(f"session : {session}")

            vram_gpu(logger=logger)

    release_cap(cap)
    release_gpu_memory(model, logger=logger)
    logger.info("✅ Analyse complète terminée.")
    return frame_data
