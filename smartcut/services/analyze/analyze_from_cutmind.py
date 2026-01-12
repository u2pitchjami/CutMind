from __future__ import annotations

from collections import Counter
from math import ceil
from pathlib import Path
import shutil

from transformers import PreTrainedModel, ProcessorMixin

from cutmind.db.repository import CutMindRepository
from cutmind.models_cm.db_models import Segment
from shared.executors.ffmpeg_utils import get_duration
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.models.timer_manager import Timer
from shared.status_orchestrator.statuses import OrchestratorStatus
from shared.utils.config import BATCH_FRAMES_DIR_SC
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from shared.utils.safe_segments import safe_segments
from smartcut.executors.analyze.analyze_batches import process_batches
from smartcut.executors.analyze.analyze_torch_utils import (
    estimate_visual_tokens,
    release_gpu_memory,
    vram_gpu,
)
from smartcut.executors.analyze.extract_frames import extract_segment_frames
from smartcut.executors.analyze.prep_analyze import cleanup_temp, open_vid, release_cap
from smartcut.executors.ia.load_model import load_and_batches
from smartcut.models_sc.ai_result import AIOutputType, AIResult
from smartcut.models_sc.ia_models import AIContext

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
    force: bool = False,
    logger: LoggerProtocol | None = None,
) -> tuple[str, str | None, list[str]]:
    """
    Extrait des frames pour chaque segment et génère les mots-clés IA.
    Retourne un mapping {segment_uid: keywords}.
    """
    logger = ensure_logger(logger, __name__)
    repo = CutMindRepository()
    try:
        # Nettoyage répertoires temporaires
        cleanup_temp()

        if not seg.description:
            seg.description = ""
        if not seg.output_path:
            raise CutMindError(
                "❌ Erreur segment : Aucune output path défini.",
                code=ErrCode.DB,
                ctx=get_step_ctx({"seg.id": seg.id}),
            )
        cap, video_name = open_vid(seg.output_path)

        # Chargement du modèle IA + paramètres de batching
        free_gb, total_gb = vram_gpu()
        logger.info(f"📊 VRAM avant chargement : {free_gb:.2f} Go / {total_gb:.2f} Go")
        processor, model, model_name, batch_size, model_precision = load_and_batches(free_gb=free_gb)
        free_vram_gb, total_vram_gb = vram_gpu()
        logger.info(
            f"🧮 VRAM libre : {free_vram_gb:.2f} Go / {total_vram_gb:.2f} Go total | "
            f"Précision : {model_precision} | Modèle : {model_name} | "
            f"→ Batch recommandé = {batch_size}"
        )

        start: float = 0.0
        if seg.duration is None:
            end: float = get_duration(Path(seg.output_path))
        else:
            end = seg.duration

        logger.info(f"🎬 Analyse segment {seg.id} ({start:.2f}s → {end:.2f}s)")

        frame_paths = extract_segment_frames(cap, video_name, start, end, auto_frames, fps_extract, base_rate)
        logger.debug(f"Extracted frame paths: {frame_paths}")
        if not frame_paths:
            logger.warning(f"Aucune frame extraite pour le segment {seg.id}")
            raise CutMindError(
                "❌ Erreur segment : Aucune frame extraite pour le segment.",
                code=ErrCode.VIDEO,
                ctx=get_step_ctx({"video_name": video_name, "seg.id": seg.id}),
            )

        if force or is_empty(seg.description) or is_empty(seg.category):
            output_type: AIOutputType = "full"
        else:
            output_type = "keywords"

        logger.info(f"🎬 Analyse segment {seg.id} ({start:.2f}s → {end:.2f}s) : {len(frame_paths)} frames extraites.")
        with Timer(f"Traitement Keywords : {seg.id}", logger):
            context = run_ai_pipeline_v25(
                video_name=video_name,
                start=start,
                end=end,
                frame_paths=frame_paths,
                categ=seg.category,
                batch_size=batch_size,
                processor=processor,
                model=model,
                output_type=output_type,
                logger=logger,
            )

        # --- DESCRIPTION ---
        if force:
            seg.description = context.description or ""
        else:
            if is_empty(seg.description) and context.description:
                seg.description = context.description or ""

        # --- CATEGORY ---
        if force:
            seg.category = context.category
        else:
            if is_empty(seg.category) and context.category:
                seg.category = context.category
        if context.keywords:
            seg.keywords = context.keywords or []
            logger.debug(f"🧠 Segment {seg.id} keywords: {seg.keywords}")
        logger.debug(f"🧠 Segment {seg.id} description: {seg.description}")

        # --- 💾 Mise à jour du segment
        logger.debug(f"🔍 seg.id={seg.id} mem_id={id(seg)}")

        seg.ai_model = model_name
        seg.status = OrchestratorStatus.SEGMENT_IA_DONE
        repo.update_segment_validation(seg)
        if not seg.id:
            raise CutMindError(
                "❌ Erreur DB : aucun seg.id.",
                code=ErrCode.DB,
                ctx=get_step_ctx({"video_name": video_name}),
            )
        if seg.keywords:
            # normalizer = KeywordNormalizer()
            # seg.keywords = normalizer.normalize_keywords(seg.keywords)
            repo.insert_keywords_standalone(segment_id=seg.id, keywords=seg.keywords)

        logger.debug(f"💾 Session mise à jour (segment {seg.id})")
        # logger.debug(f"session : {session}")

        release_cap(cap)
        free, total = vram_gpu()
        logger.info(f"📊 VRAM avant release : {free:.2f} Go / {total:.2f} Go")
        release_gpu_memory(model)
        free, total = vram_gpu()
        logger.info(f"🧹 VRAM nettoyée ('full release') → VRAM libre : {free:.2f} Go / {total:.2f} Go")
        logger.info("✅ Analyse complète terminée.")
        return seg.description, seg.category, seg.keywords
    except CutMindError as err:
        raise err.with_context(get_step_ctx({"segment_id": seg.id})) from err
    except Exception as exc:
        raise CutMindError(
            "Erreur lors du traitement IA.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"segment_id": seg.id}),
        ) from exc


def run_prompt_on_batches(
    *,
    video_name: str,
    start: float,
    end: float,
    frame_paths: list[str],
    batch_size: int,
    processor: ProcessorMixin,
    model: PreTrainedModel,
    prompt_name: str,
    system_prompt: str,
    logger: LoggerProtocol,
) -> KeywordsBatches:
    all_batches: KeywordsBatches = []

    num_batches = ceil(len(frame_paths) / batch_size)

    for b in range(num_batches):
        batch_paths = frame_paths[b * batch_size : (b + 1) * batch_size]
        if not batch_paths:
            continue

        batch_dir = (
            BATCH_FRAMES_DIR_SC / f"{video_name}_seg_{int(start * 10)}_{int(end * 10)}" / prompt_name / f"b{b + 1}"
        )
        batch_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"📁 Création répertoire batch : {batch_dir}")
        for src_path in batch_paths:
            dst_path = batch_dir / Path(src_path).name
            try:
                shutil.copy(src_path, dst_path)
            except Exception as exc:
                raise CutMindError(
                    "❌ Erreur de copie des frames.",
                    code=ErrCode.UNEXPECTED,
                    ctx=get_step_ctx(
                        {
                            "video_name": video_name,
                            "src_path": src_path,
                            "dst_path": dst_path,
                        }
                    ),
                ) from exc

        tokens, limit = estimate_visual_tokens(len(batch_paths))
        logger.info(
            "📦 Batch %d/%d | Frames=%d | Tokens=%s/%s",
            b + 1,
            num_batches,
            len(batch_paths),
            f"{tokens:,}",
            f"{limit:,}",
        )

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
        free, total = vram_gpu()
        logger.info(f"📊 VRAM avant release cache only : {free:.2f} Go / {total:.2f} Go")
        release_gpu_memory(model, cache_only=True)
        free, total = vram_gpu()
        logger.debug(f"🧹 all_batches : {all_batches}")
        logger.info(
            "🧹 VRAM nettoyée ('cache_only') → VRAM libre : %.2f Go / %.2f Go",
            free,
            total,
        )
        # delete_frames(batch_dir)

    return all_batches


def merge_description(batches: list[AIResult]) -> str | None:
    descriptions = [batch["description"] for batch in batches if batch.get("description")]
    return descriptions[-1] if descriptions else None


def merge_category(batches: list[AIResult]) -> str | None:
    categories: list[str] = []

    for batch in batches:
        keywords = batch.get("keywords")
        if keywords:
            categories.append(keywords[0])

    if not categories:
        return None

    return Counter(categories).most_common(1)[0][0]


def merge_keywords(batches: list[AIResult]) -> list[str]:
    keywords: set[str] = set()

    for batch in batches:
        batch_keywords = batch.get("keywords")
        if batch_keywords:
            keywords.update(batch_keywords)

    return sorted(keywords)


def run_ai_pipeline_v25(
    *,
    video_name: str,
    start: float,
    end: float,
    frame_paths: list[str],
    batch_size: int,
    processor: ProcessorMixin,
    model: PreTrainedModel,
    output_type: AIOutputType = "full",
    categ: str | None = None,
    logger: LoggerProtocol,
) -> AIContext:
    context = AIContext()

    if categ:
        context.category = categ
    else:
        # ===== PASSAGE 1 : description + catégorie =====
        logger.info("🧠 IA Pass 1 — Description + Catégorie")

        pass1_batches = run_prompt_on_batches(
            video_name=video_name,
            start=start,
            end=end,
            frame_paths=frame_paths,
            batch_size=batch_size,
            processor=processor,
            model=model,
            prompt_name="keywords",
            system_prompt="system_keywords",
            logger=logger,
        )

        for i, batch in enumerate(pass1_batches):
            logger.debug(
                "🧪 Batch %d → description=%s | keywords=%s",
                i,
                batch.get("description"),
                batch.get("keywords"),
            )
        context.description = merge_description(pass1_batches) or ""

        context.category = merge_category(pass1_batches)

        logger.info(
            "🧠 Pass 1 result → category=%s",
            context.category,
        )

    if not context.category:
        logger.warning("⚠️ Aucune catégorie détectée, on arrête le pipeline IA ici.")

    else:
        # ===== PASSAGE 2 : keywords guidés =====
        logger.info("🧠 IA Pass 2 — Keywords guidés : %s", context.category)

        pass2_batches = run_prompt_on_batches(
            video_name=video_name,
            start=start,
            end=end,
            frame_paths=frame_paths,
            batch_size=batch_size,
            processor=processor,
            model=model,
            prompt_name=context.category,
            system_prompt="system_keywords",
            logger=logger,
        )

        context.keywords = merge_keywords(pass2_batches)
        for i, batch in enumerate(pass2_batches):
            logger.debug(
                "🧪 Batch %d → description=%s | keywords=%s",
                i,
                batch.get("description"),
                batch.get("keywords"),
            )

    return context


def is_empty(value: str | None) -> bool:
    return value is None or not value.strip()
