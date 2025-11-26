# smartcut/services/analyze/apply_results.py

from __future__ import annotations

from datetime import datetime

from shared.utils.logger import LoggerProtocol, ensure_logger
from smartcut.models_sc.smartcut_model import SmartCutSession
from smartcut.services.analyze.ia_models import IASegmentResult


def apply_ia_results_to_session(
    session: SmartCutSession,
    results: list[IASegmentResult],
    *,
    logger: LoggerProtocol | None = None,
) -> None:
    """
    Applique les résultats IA (description + keywords + erreurs)
    aux segments d'une session SmartCut.

    Compatible FULL et LITE.
    """
    logger = ensure_logger(logger, __name__)
    result_by_id = {res.segment_id: res for res in results}

    for seg in session.segments:
        res = result_by_id.get(seg.id)
        if res is None:
            continue

        if res.error:
            seg.ai_status = "failed"
            seg.error = res.error
            session.errors.append(res.error)
            logger.warning(f"⚠️ Segment {seg.id} marqué failed : {res.error}")
            continue

        # Résultats corrects
        seg.description = res.description
        seg.keywords = res.keywords
        seg.ai_model = res.model_name
        seg.ai_status = "done"
        seg.status = "ia_done"
        seg.last_updated = datetime.now().isoformat()

        logger.info(f"🧠 Segment {seg.id} mis à jour → {len(seg.keywords)} keywords, model={seg.ai_model}")

    # Mise à jour du statut global
    if all(s.ai_status == "done" for s in session.segments):
        session.status = "ia_done"
    else:
        logger.warning("🚧 Certains segments IA n’ont pas été traités complètement.")
