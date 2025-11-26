# smartcut/services/db_pipeline.py

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from cutmind.db.repository import CutMindRepository
from cutmind.models_cm.db_models import Segment, Video
from shared.models.timer_manager import Timer
from shared.services.video_preparation import prepare_video
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from smartcut.analyze.analyze_confidence import compute_confidence
from smartcut.analyze.analyze_utils import extract_keywords_from_filename
from smartcut.services.analyze.ia_pipeline_service import run_ia_pipeline
from smartcut.services.scene_split.pipeline_service import adaptive_scene_split

repo = CutMindRepository()


@with_child_logger
def run_smartcut_db_pipeline(
    video_path: Path,
    *,
    lite: bool = False,
    logger: LoggerProtocol | None = None,
) -> None:
    """
    Pipeline SmartCut 100% basé DB.
    Ne touche jamais aux JSON.
    """
    logger = ensure_logger(logger, __name__)
    logger.info("🚀 Lancement SmartCut → DB : %s (lite=%s)", video_path, lite)

    # -------------------------------------------------------
    #  1) Enregistrement vidéo (si pas déjà en DB)
    # -------------------------------------------------------
    prep = prepare_video(video_path)
    video_uid = str(uuid4())

    video = Video(
        uid=video_uid,
        name=video_path.name,
        duration=prep.duration,
        fps=prep.fps,
        resolution=prep.resolution,
        codec=prep.codec,
        bitrate=prep.bitrate,
        filesize_mb=prep.filesize_mb,
        status="init",
        origin="smartcut_lite" if lite else "smartcut",
    )

    video_id = repo.insert_video_with_segments(video)
    logger.info("🎬 Vidéo enregistrée en DB id=%s", video_id)

    # On recharge pour avoir video.id + segments (même si pas encore créés)
    video = repo.get_video_with_segments(video_id=video_id)

    # -------------------------------------------------------
    #  2) Split → création segments en DB
    # -------------------------------------------------------
    if not lite:
        with Timer("Split vidéo", logger):
            timings = adaptive_scene_split(video_path)

            segments_db = []
            for idx, (start, end) in enumerate(timings, start=1):
                seg = Segment(
                    uid=str(uuid4()),
                    video_id=video.id,
                    start=start,
                    end=end,
                    duration=end - start,
                    status="wait_ia",
                    created_at=datetime.now(),
                    last_updated=datetime.now(),
                )
                segments_db.append(seg)

            video.segments = segments_db
            repo.insert_video_with_segments(video)
            logger.info("✂️ %d segments enregistrés en DB", len(segments_db))

    else:
        # --- Mode Lite : segments déjà présents dans un dossier ---
        from smartcut.lite.scan_lite_segments import find_lite_segments

        segments_db = find_lite_segments(video_path, video_id, logger=logger)
        logger.info("📦 %d segments Lite trouvés", len(segments_db))

        # Insertion des segments
        with repo.transaction(logger=logger) as conn:
            with conn.cursor() as cur:
                for seg in segments_db:
                    repo._insert_segment(seg, cur, logger=logger)
            conn.commit()

        video = repo.get_video_with_segments(video_id=video_id)

    # -------------------------------------------------------
    #  3) IA
    # -------------------------------------------------------
    pending = [s for s in video.segments if s.status == "wait_ia"]

    if pending:
        ia_results = run_ia_pipeline(
            video_path=str(video_path),
            segments=pending,
            lite=lite,
            logger=logger,
        )

        for res in ia_results:
            seg = next((s for s in video.segments if s.id == res.segment_id), None)
            if not seg:
                continue

            if res.error:
                seg.status = "failed"
                seg.error = res.error
                repo.update_segment_validation(seg, logger=logger)
                continue

            # IA OK
            seg.description = res.description
            seg.ai_model = res.model_name
            seg.status = "ia_done"
            seg.last_updated = datetime.now()

            repo.update_segment_validation(seg, logger=logger)
            repo.insert_keywords_standalone(seg.id, res.keywords, logger=logger)

    repo.update_video(video, logger=logger)

    # -------------------------------------------------------
    #  4) Confidence + enrich keywords
    # -------------------------------------------------------
    auto_keywords = extract_keywords_from_filename(video.name)
    confidence_updated = 0

    for seg in repo.get_video_with_segments(video_id=video_id).segments:
        if seg.status != "ia_done":
            continue

        score = compute_confidence(seg.description or "", seg.keywords, logger=logger)
        seg.confidence = score
        seg.status = "confidence_done"

        # merge
        merged = list({*seg.keywords, *auto_keywords})
        repo.insert_keywords_standalone(seg.id, merged, logger=logger)

        repo.update_segment_validation(seg, logger=logger)
        confidence_updated += 1

    logger.info("📊 Confidence calculée pour %d segments", confidence_updated)

    # -------------------------------------------------------
    #  5) Cut final
    # -------------------------------------------------------
    for seg in repo.get_video_with_segments(video_id=video_id).segments:
        if seg.status != "confidence_done":
            continue

        output = cut_segment_file(video_path, seg.start, seg.end, seg.uid)

        seg.output_path = output
        seg.status = "cut_done"
        repo.update_segment_validation(seg, logger=logger)

    # -------------------------------------------------------
    #  FIN
    # -------------------------------------------------------
    video.status = "smartcut_done"
    repo.update_video(video, logger=logger)
    logger.info("🏁 SmartCut terminé pour %s", video_path)
