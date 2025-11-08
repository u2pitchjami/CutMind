"""
Analyse et validation automatique des segments (v3.2)
=====================================================

Cette version opère directement depuis la base de données via CutMindRepository.

Règle de validation :
---------------------
- Un segment est "validated" si :
    • description non vide
    • confidence >= min_confidence
    • au moins 1 mot-clé

Sinon → "pending_check" + source_flow = "manual_review"

Si *tous* les segments d'une vidéo sont validés :
    - La vidéo est considérée comme "validated"
    - Les segments peuvent être déplacés / traités ensuite
"""

from __future__ import annotations

from typing import Any

from cutmind.db.repository import CutMindRepository
from cutmind.models.db_models import Video
from cutmind.process.file_mover import CUTMIND_BASEDIR, FileMover, sanitize
from shared.utils.logger import get_logger

logger = get_logger(__name__)


# =====================================================================
# ⚙️ Validation automatique d'une vidéo
# =====================================================================


def analyze_session_validation_db(video: Video, min_confidence: float = 0.45) -> dict[str, Any]:
    repo = CutMindRepository()
    if not video:
        logger.warning("⚠️ Vidéo introuvable")
        return {"valid": 0, "total": 0, "auto_valid": False}

    total = len(video.segments)
    valid_segments = []
    decisions = []

    logger.info("🔎 Analyse validation pour %s (%d segments)", video.name, total)

    # --- Analyse en mémoire ---
    for seg in video.segments:
        desc_ok = bool(seg.description and seg.description.strip().lower() not in ("none", ""))
        conf_ok = (seg.confidence or 0.0) >= min_confidence
        kw_ok = bool(seg.keywords and len(seg.keywords) > 0)

        if desc_ok and conf_ok and kw_ok:
            seg.status = "validated"
            if seg.source_flow == "manual_review":
                logger.info("♻️ Segment re-validé automatiquement : %s", seg.uid)
                seg.source_flow = "manual_validation"
            else:
                seg.source_flow = "auto_validation"
            valid_segments.append(seg)
        else:
            seg.status = "pending_check"
            seg.source_flow = "manual_review"

        decisions.append(seg)

    valid_count = len(valid_segments)
    auto_valid = valid_count == total

    # --- Si pas auto-validée : mise à jour simple ---
    if not auto_valid:
        with repo.transaction():
            for seg in decisions:
                repo.update_segment_validation(seg)
            video.status = "manual_review"
            repo.update_video(video)

        logger.info("🕵️ Validation partielle : %s (%d/%d segments)", video.name, valid_count, total)
        return {
            "uid": video.uid,
            "valid": valid_count,
            "total": total,
            "auto_valid": False,
            "moved": False,
        }

    # --- Auto-validation complète : tentative de déplacement ---
    mover = FileMover()

    # Plan des destinations (relatives)
    planned_targets = {}
    safe_name = sanitize(video.name)
    for seg in valid_segments:
        if not seg.filename_predicted:
            logger.error("❌ Segment sans fichier prédit : %s (vidéo %s)", seg.uid, video.name)
            return {
                "uid": video.uid,
                "valid": valid_count,
                "total": total,
                "auto_valid": False,
                "moved": False,
            }
        dst_final = CUTMIND_BASEDIR / safe_name / seg.filename_predicted
        dst_rel = dst_final
        planned_targets[seg.uid] = dst_rel

    moved_ok = mover.move_video_files(video, planned_targets)

    if not moved_ok:
        logger.error("❌ Échec déplacement fichiers pour %s — aucun changement DB", video.name)
        return {
            "uid": video.uid,
            "valid": valid_count,
            "total": total,
            "auto_valid": True,
            "moved": False,
        }

    # --- Déplacement réussi : commit DB ---
    with repo.transaction():
        for seg in valid_segments:
            seg.output_path = str(planned_targets[seg.uid])
            repo.update_segment_validation(seg)

        video.status = "validated"
        repo.update_video(video)

    logger.info("✅ Auto-validation + déplacement : %s (%d segments)", video.name, valid_count)

    return {
        "uid": video.uid,
        "valid": valid_count,
        "total": total,
        "auto_valid": True,
        "moved": True,
    }
