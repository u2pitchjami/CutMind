# smartcut/services/analyze/apply_confidence.py

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from cutmind.db.repository import CutMindRepository
from cutmind.models_cm.db_models import Segment, Video
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.status_orchestrator.statuses import SegmentStatus
from shared.utils.logger import LoggerProtocol, ensure_logger
from smartcut.executors.analyze.analyze_torch_utils import release_gpu_memory, vram_gpu
from smartcut.executors.analyze.analyze_utils import extract_keywords_from_filename
from smartcut.services.analyze.confidence_service import ConfidenceService


def apply_confidence_to_session(
    session: Video,
    segments: list[Segment],
    model_name: str,
    logger: LoggerProtocol | None = None,
) -> None:
    """
    Applique le calcul de confiance via ConfidenceService
    et fusionne les mots-clés automatiques.

    Compatible FULL et LITE.
    """
    logger = ensure_logger(logger, __name__)
    if not session.video_path:
        raise CutMindError(
            "❌ La session n'a pas de video_path défini.",
            code=ErrCode.NOFILE,
            ctx=get_step_ctx({"video": session.name}),
        )
    base_name = Path(session.video_path).stem
    repo = CutMindRepository()

    try:
        free_gb, total_gb = vram_gpu()
        logger.info(f"📊 VRAM avant chargement : {free_gb:.2f} Go / {total_gb:.2f} Go")

        auto_keywords = extract_keywords_from_filename(base_name)
        logger.debug(f"🔑 Mots-clés automatiques extraits du nom de la vidéo : {auto_keywords}")

        # 👉 Service métier (qui utilise ton ConfidenceExecutor)
        service = ConfidenceService(model_name=model_name)

        # 👉 Calcul batch sur segments
        results = service.compute_for_segments(
            segments=segments,
            auto_keywords=auto_keywords,
        )

        release_gpu_memory(model_name, cache_only=True)
        free, total = vram_gpu()
        logger.info(
            "🧹 VRAM nettoyée ('cache_only') → VRAM libre : %.2f Go / %.2f Go",
            free,
            total,
        )

        # 🔁 Mise à jour de la session
        for res in results:
            seg = next((s for s in session.segments if s.id == res.segment_id), None)
            if seg is None or not seg.id:
                continue

            seg.confidence = res.confidence
            seg.keywords = res.merged_keywords
            seg.status = SegmentStatus.CONFIDENCE_DONE
            seg.last_updated = datetime.now().isoformat()

            repo.update_segment_validation(seg)
            repo.insert_keywords_standalone(seg.id, seg.keywords)

            logger.info(f"🔎 Segment {seg.id}: confidence={seg.confidence:.3f} | keywords={seg.keywords}")

    except CutMindError as err:
        raise err.with_context(get_step_ctx({"video": session.name})) from err
    except Exception as exc:
        raise CutMindError(
            "Erreur lors du traitement IA Confidence.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video": session.name}),
        ) from exc
