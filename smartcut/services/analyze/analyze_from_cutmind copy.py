from __future__ import annotations

from math import ceil
from pathlib import Path
import shutil

from cutmind.db.repository import CutMindRepository
from cutmind.models_cm.db_models import Segment
from shared.executors.ffmpeg_utils import get_duration
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.models.timer_manager import Timer
from shared.utils.config import BATCH_FRAMES_DIR_SC
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from shared.utils.safe_segments import safe_segments
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
from smartcut.services.keyword_normalizer import KeywordNormalizer

KeywordsBatches = list[AIResult]


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
    prompt_name: str = "keywords",
    system_prompt: str = "system_keywords",
    logger: LoggerProtocol | None = None,
) -> tuple[str, list[str]]:
    """
    Extrait des frames pour chaque segment et génère les mots-clés IA.
    Retourne un mapping {segment_uid: keywords}.
    """
    logger = ensure_logger(logger, __name__)
    repo = CutMindRepository()
    try:
        # Nettoyage répertoires temporaires
        cleanup_temp()

        if not seg.output_path:
            raise CutMindError(
                "❌ Erreur segment : Aucune output path défini.",
                code=ErrCode.DB,
                ctx=get_step_ctx({"seg.id": seg.id}),
            )

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

        start: float = 0.0
        if seg.duration is None:
            end: float = get_duration(Path(seg.output_path))
        else:
            end = seg.duration

        logger.info(f"🎬 Analyse segment {seg.id} ({start:.2f}s → {end:.2f}s)")

        cap, video_name = open_vid(seg.output_path)
        frame_paths = extract_segment_frames(cap, video_name, start, end, auto_frames, fps_extract, base_rate)
        if not frame_paths:
            logger.warning(f"Aucune frame extraite pour le segment {seg.id}")
            raise CutMindError(
                "❌ Erreur segment : Aucune frame extraite pour le segment.",
                code=ErrCode.VIDEO,
                ctx=get_step_ctx({"video_name": video_name, "seg.id": seg.id}),
            )

        logger.info(f"🎬 Analyse segment {seg.id} ({start:.2f}s → {end:.2f}s) : {len(frame_paths)} frames extraites.")

        with Timer(f"Traitement Keywords : {seg.id}", logger):
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
                    except Exception as exc:
                        raise CutMindError(
                            "❌ Erreur de copie des frames.",
                            code=ErrCode.UNEXPECTED,
                            ctx=get_step_ctx({"video_name": video_name, "src_path": src_path, "dst_path": dst_path}),
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
                    prompt_name=prompt_name,
                    system_prompt=system_prompt,
                )
                all_batches.append(batch_result)
                release_gpu_memory(model, cache_only=True)
                free, total = vram_gpu()
                logger.info(
                    f"🧹 VRAM nettoyée ('cache_only') → VRAM libre : {free / 1e9:.2f} Go / {total / 1e9:.2f} Go"
                )
        delete_frames(batch_dir)
        # Fusion des résultats IA
        normalizer = KeywordNormalizer()
        merged_description, keywords_list = merge_keywords_across_batches(all_batches, normalizer=normalizer)
        logger.debug(f"🧠 Segment {seg.id} description: {merged_description}")
        logger.debug(f"🧠 Segment {seg.id} keywords: {keywords_list}")

        # --- 💾 Mise à jour du segment
        logger.debug(f"🔍 seg.id={seg.id} mem_id={id(seg)}")

        seg.description = merged_description
        seg.keywords = keywords_list
        seg.ai_model = model_name
        repo.update_segment_validation(seg)
        if not seg.id:
            raise CutMindError(
                "❌ Erreur DB : aucun seg.id.",
                code=ErrCode.DB,
                ctx=get_step_ctx({"video_name": video_name}),
            )
        repo.insert_keywords_standalone(segment_id=seg.id, keywords=seg.keywords)

        logger.debug(f"💾 Session mise à jour (segment {seg.id})")
        # logger.debug(f"session : {session}")

        release_cap(cap)
        release_gpu_memory(model)
        free, total = vram_gpu()
        logger.info(f"🧹 VRAM nettoyée ('full release') → VRAM libre : {free / 1e9:.2f} Go / {total / 1e9:.2f} Go")
        logger.info("✅ Analyse complète terminée.")
        return seg.description, seg.keywords
    except CutMindError as err:
        raise err.with_context(get_step_ctx({"segment_id": seg.id})) from err
    except Exception as exc:
        raise CutMindError(
            "Erreur lors du traitement IA.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"segment_id": seg.id}),
        ) from exc
