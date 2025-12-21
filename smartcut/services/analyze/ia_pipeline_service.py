from __future__ import annotations

from math import ceil
from pathlib import Path
import shutil

from cutmind.db.repository import CutMindRepository
from cutmind.models_cm.db_models import Segment
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.models.timer_manager import Timer
from shared.utils.config import BATCH_FRAMES_DIR_SC
from shared.utils.logger import LoggerProtocol, ensure_logger
from smartcut.executors.analyze.analyze_batches import process_batches
from smartcut.executors.analyze.analyze_torch_utils import (
    estimate_visual_tokens,
    release_gpu_memory,
    vram_gpu,
)
from smartcut.executors.analyze.analyze_utils import (
    delete_frames,
    merge_keywords_across_batches,
)
from smartcut.executors.analyze.extract_frames import extract_segment_frames
from smartcut.executors.analyze.prep_analyze import cleanup_temp, open_vid, release_cap
from smartcut.executors.ia.load_model import load_and_batches
from smartcut.models_sc.ai_result import AIResult
from smartcut.models_sc.ia_models import IASegmentResult
from smartcut.services.keyword_normalizer import KeywordNormalizer

KeywordsBatches = list[AIResult]


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

    try:
        # Nettoyage des répertoires temporaires (frames & batches)
        cleanup_temp()

        cap = None
        video_name = None

        if not lite:
            # Mode complet : on ouvre UNE seule fois la vidéo source
            cap, video_name = open_vid(video_path)
            logger.debug("🔵 Mode COMPLET – vidéo source ouverte : %s", video_name)

        # Chargement du modèle IA + paramètres de batching
        free_gb, total_gb = vram_gpu()
        logger.info(f"📊 VRAM avant chargement : {free_gb:.2f} Go / {total_gb:.2f} Go")
        processor, model, model_name, batch_size, model_precision = load_and_batches(free_gb=free_gb)
        free_vram_gb, total_vram_gb = vram_gpu()
        logger.info(
            f"🧮 VRAM libre : {free_vram_gb:.2f} Go / {total_vram_gb / 1e9:.2f} Go total | "
            f"Précision : {model_precision} | Modèle : {model_name} | "
            f"→ Batch recommandé = {batch_size}"
        )

        with Timer("Traitement IA segments", logger):
            for seg in segments:
                try:
                    # En mode orchestration global, tu filtres déjà les pending_segments
                    if not seg or not seg.id:
                        logger.warning("⚠️ Segment invalide ou sans ID, on l'ignore.")
                        continue
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
                            cap, video_name = open_vid(str(seg_video_path))
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
                        all_batches: KeywordsBatches = []
                        num_batches = ceil(len(frame_paths) / batch_size)
                        for b in range(num_batches):
                            batch_paths = frame_paths[b * batch_size : (b + 1) * batch_size]
                            if not batch_paths:
                                continue
                            batch_dir = (
                                BATCH_FRAMES_DIR_SC / f"{video_name}_seg_{int(start * 10)}_{int(end * 10)}_b{b + 1}"
                            )
                            batch_dir.mkdir(parents=True, exist_ok=True)

                            for src_path in batch_paths:
                                dst_path = batch_dir / Path(src_path).name
                                try:
                                    shutil.copy(src_path, dst_path)
                                except Exception as exc:
                                    raise CutMindError(
                                        "❌ Erreur de copie des frames.",
                                        code=ErrCode.UNEXPECTED,
                                        ctx=get_step_ctx(
                                            {"video_name": video_name, "src_path": src_path, "dst_path": dst_path}
                                        ),
                                    ) from exc

                            logger.info(f"📦 Batch {b + 1}/{num_batches} → {len(batch_paths)} frames.")
                            tokens, limit = estimate_visual_tokens(len(batch_paths))
                            logger.info(f"🧮 Contexte : {tokens:,} / {limit:,}")

                            batch_result = process_batches(
                                video_name=video_name,
                                start=start,
                                end=end,
                                frame_paths=frame_paths,
                                batch_size=batch_size,
                                batch_dir=batch_dir,
                                batch_paths=batch_paths,
                                processor=processor,
                                model=model,
                            )
                            all_batches.append(batch_result)
                            release_gpu_memory(model, cache_only=True)
                            free, total = vram_gpu()
                            logger.info(
                                f"🧹 VRAM nettoyée ('cache_only') → VRAM libre :\
                                    {free / 1e9:.2f} Go / {total / 1e9:.2f} Go"
                            )

                    delete_frames(batch_dir)
                    # 3) Fusion des résultats IA
                    normalizer = KeywordNormalizer()
                    merged_description, keywords_list = merge_keywords_across_batches(
                        all_batches,
                        normalizer=normalizer,
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
                    repo.insert_keywords_standalone(segment_id=seg.id, keywords=seg.keywords)

                    # monitoring mémoire GPU
                    free_gb, total_gb = vram_gpu()
                    logger.info(f"📊 VRAM post traitement seg {seg.id} : {free_gb:.2f} Go / {total_gb:.2f} Go")
                    # en mode LITE, on ferme le cap à chaque segment
                    if lite:
                        release_cap(cap)
                        cap = None
                        video_name = None

                except CutMindError as err:
                    raise err.with_context(get_step_ctx({"segment_id": seg.id})) from err
                except Exception as exc:
                    raise CutMindError(
                        "❌ Erreur lors du traitement IA.",
                        code=ErrCode.UNEXPECTED,
                        ctx=get_step_ctx({"segment_id": seg.id}),
                    ) from exc

        # Fin de pipeline : libération des ressources
        if cap is not None:
            release_cap(cap)
        release_gpu_memory(model)
        free, total = vram_gpu()
        logger.info(f"🧹 VRAM nettoyée ('full release') → VRAM libre : {free / 1e9:.2f} Go / {total / 1e9:.2f} Go")
        logger.info("✅ Analyse IA complète terminée (%d segments).", len(results))

        return results
    except CutMindError as err:
        raise err.with_context(get_step_ctx({"segment_id": seg.id})) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur lors du traitement IA.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"segment_id": seg.id}),
        ) from exc
