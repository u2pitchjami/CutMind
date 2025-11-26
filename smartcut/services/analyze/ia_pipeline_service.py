from __future__ import annotations

from pathlib import Path

from cutmind.db.repository import CutMindRepository
from cutmind.models_cm.db_models import Segment
from shared.models.exceptions import CutMindError, ErrCode
from shared.models.timer_manager import Timer
from shared.utils.logger import LoggerProtocol, ensure_logger
from smartcut.analyze.analyze_batches import process_batches
from smartcut.analyze.analyze_torch_utils import release_gpu_memory, vram_gpu
from smartcut.analyze.analyze_utils import merge_keywords_across_batches
from smartcut.analyze.extract_frames import extract_segment_frames
from smartcut.analyze.prep_analyze import cleanup_temp, open_vid, release_cap
from smartcut.gen_keywords.load_model import load_and_batches
from smartcut.services.analyze.ia_models import IASegmentResult


def run_ia_pipeline(
    video_path: str,
    segments: list[Segment],
    *,
    frames_per_segment: int = 3,  # réservé si tu veux forcer à terme
    auto_frames: bool = True,
    base_rate: int = 5,
    fps_extract: float = 1.0,
    lite: bool = False,
    logger: LoggerProtocol | None = None,
) -> list[IASegmentResult]:
    """
    Pipeline IA unifié pour SmartCut.

    - mode complet : utilise la vidéo source (video_path) + start/end segments
    - mode lite    : ouvre chaque fichier segment (seg.output_path) et analyse localement

    Retourne une liste de IASegmentResult (description + keywords + erreurs éventuelles).
    """
    logger = ensure_logger(logger, __name__)
    results: list[IASegmentResult] = []
    repo = CutMindRepository()
    # Nettoyage des répertoires temporaires (frames & batches)
    cleanup_temp(logger=logger)

    cap = None
    video_name = None

    if not lite:
        # Mode complet : on ouvre UNE seule fois la vidéo source
        cap, video_name = open_vid(video_path, logger=logger)
        logger.debug("🔵 Mode COMPLET – vidéo source ouverte : %s", video_name)

    # Chargement du modèle IA + paramètres de batching
    processor, model, model_name, batch_size = load_and_batches(logger=logger)
    logger.info("🧠 Modèle IA chargé : %s | batch_size=%d", model_name, batch_size)

    with Timer("Traitement IA segments", logger):
        for seg in segments:
            # En mode orchestration global, tu filtres déjà les pending_segments
            start = seg.start
            end = seg.end

            # Détermination de la source vidéo selon le mode
            if lite:
                if not seg.output_path:
                    msg = f"Chemin de segment vide pour le segment {seg.id} en mode LITE."
                    logger.error(msg)
                    results.append(
                        IASegmentResult(
                            segment_id=seg.id,
                            description="",
                            keywords=[],
                            model_name=model_name,
                            error=msg,
                        )
                    )
                    continue

                seg_video_path = Path(seg.output_path)
                try:
                    cap, video_name = open_vid(str(seg_video_path), logger=logger)
                except Exception as exc:  # pylint: disable=broad-except
                    msg = f"Impossible d'ouvrir la vidéo segment {seg_video_path}"
                    logger.error("%s : %s", msg, exc)
                    results.append(
                        IASegmentResult(
                            segment_id=seg.id,
                            description="",
                            keywords=[],
                            model_name=model_name,
                            error=msg,
                        )
                    )
                    continue

                logger.debug("🟢 Mode LITE – ouverture vidéo segment : %s", video_name)

            if cap is None or video_name is None:
                raise CutMindError(
                    "Capteur vidéo non initialisé avant extraction des frames.",
                    code=ErrCode.UNEXPECTED,
                    ctx={"segment_id": seg.id, "lite": lite},
                )

            logger.info("🎬 Analyse segment %d (%.2fs → %.2fs)", seg.id, start, end)

            # 1) Extraction des frames
            frame_paths = extract_segment_frames(
                cap=cap,
                video_name=video_name,
                start=start,
                end=end,
                auto_frames=auto_frames,
                fps_extract=fps_extract,
                base_rate=base_rate,
                logger=logger,
            )

            if not frame_paths:
                msg = f"Aucune frame extraite pour le segment {seg.id}"
                logger.warning("⚠️ %s", msg)
                results.append(
                    IASegmentResult(
                        segment_id=seg.id,
                        description="",
                        keywords=[],
                        model_name=model_name,
                        error=msg,
                    )
                )

                if lite:
                    release_cap(cap)
                    cap = None
                    video_name = None

                continue

            # 2) IA par lots
            with Timer(f"Traitement Keywords segment {seg.id}", logger):
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

            # 3) Fusion des résultats IA
            merged_description, keywords_list = merge_keywords_across_batches(
                keywords_batches,
                logger=logger,
            )
            logger.debug("🧠 Segment %d description: %s", seg.id, merged_description[:120])
            logger.debug("🧠 Segment %d keywords: %s", seg.id, keywords_list)

            results.append(
                IASegmentResult(
                    segment_id=seg.id,
                    description=merged_description,
                    keywords=keywords_list,
                    model_name=model_name,
                    error=None,
                )
            )
            seg.description = merged_description
            seg.keywords = keywords_list
            seg.ai_model = model_name
            seg.status = "ia_done"
            repo.update_segment_validation(seg)

            # monitoring mémoire GPU
            vram_gpu(logger=logger)

            # en mode LITE, on ferme le cap à chaque segment
            if lite:
                release_cap(cap)
                cap = None
                video_name = None

    # Fin de pipeline : libération des ressources
    if cap is not None:
        release_cap(cap)
    release_gpu_memory(model, logger=logger)
    logger.info("✅ Analyse IA complète terminée (%d segments).", len(results))

    return results
