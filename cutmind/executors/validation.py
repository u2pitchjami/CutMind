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
from cutmind.models_cm.db_models import Video
from cutmind.process.file_mover import CUTMIND_BASEDIR, FileMover, sanitize
from cutmind.services.categ.categ_serv import match_category
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.config import OUTPUT_DIR_SC
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from shared.utils.remove_empty_dirs import remove_empty_dirs
from shared.utils.safe_segments import safe_segments
from smartcut.services.analyze.analyze_from_cutmind import analyze_from_cutmind


# =====================================================================
# ⚙️ Validation automatique d'une vidéo
# =====================================================================
@safe_segments
@with_child_logger
def analyze_session_validation_db(
    video: Video, min_confidence: float = 0.45, logger: LoggerProtocol | None = None
) -> dict[str, Any]:
    logger = ensure_logger(logger, __name__)
    repo = CutMindRepository()
    if not video:
        raise CutMindError("❌ Erreur vidéo absente pour la validation.", code=ErrCode.NOFILE, ctx=get_step_ctx())

    total = len(video.segments)
    valid_segments = []
    decisions = []

    # --- Analyse en mémoire ---
    try:
        for seg in video.segments:
            if not seg.description and not seg.confidence and not seg.keywords:
                seg.description, seg.keywords = analyze_from_cutmind(seg, logger)
            desc_ok = bool(seg.description and seg.description.strip().lower() not in ("none", ""))
            conf_ok = (seg.confidence or 0.0) >= min_confidence
            kw_ok = bool(seg.keywords and len(seg.keywords) > 0)

            if desc_ok and conf_ok and kw_ok:
                seg.status = "validated"
                seg.category = match_category(seg.keywords)
                if seg.category and seg.category.strip().lower() not in ("none", ""):
                    if seg.source_flow == "manual_review":
                        seg.source_flow = "manual_validation"
                    else:
                        seg.source_flow = "auto_validation"
                    valid_segments.append(seg)
                else:
                    seg.status = "pending_check"
                    seg.source_flow = "manual_review"
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

        remove_empty_dirs(root_path=OUTPUT_DIR_SC)

        return {
            "uid": video.uid,
            "valid": valid_count,
            "total": total,
            "auto_valid": True,
            "moved": True,
        }
    except CutMindError as err:
        raise err.with_context(get_step_ctx({"name": video.name})) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur innatendue lors de la validation.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"name": video.name}),
        ) from exc
