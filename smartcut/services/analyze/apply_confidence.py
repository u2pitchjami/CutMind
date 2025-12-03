# smartcut/services/analyze/apply_confidence.py

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from cutmind.db.repository import CutMindRepository
from cutmind.models_cm.db_models import Video
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.logger import LoggerProtocol, ensure_logger
from smartcut.executors.analyze.analyze_utils import extract_keywords_from_filename
from smartcut.services.analyze.confidence_service import ConfidenceService


def apply_confidence_to_session(
    session: Video,
    *,
    video_or_dir_name: str | Path,
    model_name: str,
    logger: LoggerProtocol | None = None,
) -> None:
    """
    Applique le calcul de confiance via ConfidenceService
    et fusionne les mots-clés automatiques.

    Compatible FULL et LITE.
    """
    logger = ensure_logger(logger, __name__)
    base_name = Path(video_or_dir_name).stem
    repo = CutMindRepository()

    try:
        auto_keywords = extract_keywords_from_filename(base_name)

        # 👉 Service métier (qui utilise ton ConfidenceExecutor)
        service = ConfidenceService(model_name=model_name)

        # 👉 Calcul batch sur segments
        results = service.compute_for_segments(
            segments=session.segments,
            auto_keywords=auto_keywords,
        )

        # 🔁 Mise à jour de la session
        for res in results:
            seg = next((s for s in session.segments if s.id == res.segment_id), None)
            if seg is None:
                continue

            seg.confidence = res.confidence
            seg.keywords = res.merged_keywords
            seg.status = "confidence_done"
            seg.last_updated = datetime.now().isoformat()

            repo.update_segment_validation(seg)

            logger.info(f"🔎 Segment {seg.id}: confidence={seg.confidence:.3f} | keywords={seg.keywords}")

        # 🎯 Statut global
        if all(s.status == "confidence_done" for s in session.segments):
            session.status = "confidence_done"
            repo.update_video(session)
        else:
            logger.warning("🚧 Certains segments n'ont pas pu être mis à jour.")
    except CutMindError as err:
        raise err.with_context(get_step_ctx({"video": session.name})) from err
    except Exception as exc:
        raise CutMindError(
            "Erreur lors du traitement IA Confidence.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video": session.name}),
        ) from exc
