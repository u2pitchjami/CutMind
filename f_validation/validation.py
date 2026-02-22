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

from b_db.repository import CutMindRepository
from g_check.histo.processing_log import processing_step
from shared.models.db_models import Segment, Video
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.services.file_mover import CUTMIND_BASEDIR, FileMover, sanitize
from shared.status_orchestrator.statuses import OrchestratorStatus
from shared.utils.config import OUTPUT_DIR_SC
from shared.utils.logger import LoggerProtocol, ensure_logger
from shared.utils.remove_empty_dirs import remove_empty_dirs
from shared.utils.safe_segments import safe_segments


# =====================================================================
# ⚙️ Validation automatique d'une vidéo
# =====================================================================
@safe_segments
def validation_db(
    video: Video, segments: list[Segment], min_confidence: float = 0.45, logger: LoggerProtocol | None = None
) -> dict[str, Any]:
    logger = ensure_logger(logger, __name__)
    repo = CutMindRepository()
    if not video:
        raise CutMindError("❌ Erreur vidéo absente pour la validation.", code=ErrCode.NOFILE, ctx=get_step_ctx())

    total = len(segments)
    valid_segments = []
    decisions = []

    # --- Analyse en mémoire ---
    try:
        for seg in segments:
            with processing_step(video, seg, action="Validation") as history:
                desc_ok = bool(seg.description and seg.description.strip().lower() not in ("none", ""))
                cat_ok = bool(seg.category and seg.category.strip().lower() not in ("none", ""))
                conf_ok = (seg.confidence or 0.0) >= min_confidence
                kw_ok = bool(seg.keywords and len(seg.keywords) > 0)

                if desc_ok and cat_ok and conf_ok and kw_ok:
                    valid_segments.append(seg)
                    history.status = "ok"
                    history.message = f"Validation (confiance = {seg.confidence:.2f})"
                else:
                    decisions.append(seg)
                    history.status = "ko"
                    problems = []
                    if not desc_ok:
                        problems.append("description manquante")
                    if not cat_ok:
                        problems.append("catégorie absente")
                    if not kw_ok:
                        problems.append("aucun mot-clé")
                    if not conf_ok:
                        problems.append(f"confiance trop faible ({seg.confidence:.2f})")

                    history.message = "Validation KO : " + ", ".join(problems)

        valid_count = len(valid_segments)
        # auto_valid = valid_count == total

        # --- Si pas auto-validée : mise à jour simple ---
        if decisions:
            with repo.transaction():
                for seg in decisions:
                    seg.pipeline_target = OrchestratorStatus.SEGMENT_PENDING_CHECK
                    repo.update_segment_validation(seg)
        if valid_segments:
            with repo.transaction():
                for seg in valid_segments:
                    seg.status = OrchestratorStatus.SEGMENT_VALIDATED
                    seg.pipeline_target = None
                    repo.update_segment_validation(seg)

        remove_empty_dirs(root_path=OUTPUT_DIR_SC, logger=logger)

        return {
            "uid": video.uid,
            "valid": valid_count,
            "total": total,
            "moved": False,
        }

    except CutMindError as err:
        raise err.with_context(get_step_ctx({"name": video.name})) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur innatendue lors de la validation.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"name": video.name}),
        ) from exc


@safe_segments
def validation_cut(
    video: Video, segments: list[Segment], min_confidence: float = 0.45, logger: LoggerProtocol | None = None
) -> dict[str, Any]:
    logger = ensure_logger(logger, __name__)
    logger.debug("🔍 Validation CUT pour la vidéo %s", video.name)
    repo = CutMindRepository()
    if not video:
        raise CutMindError("❌ Erreur vidéo absente pour la validation.", code=ErrCode.NOFILE, ctx=get_step_ctx())

    total = len(segments)
    logger.debug("🔍 Total segments à valider : %d", total)
    valid_segments = []

    # --- Analyse en mémoire ---
    try:
        for seg in segments:
            if seg.status == OrchestratorStatus.SEGMENT_CUT_VALIDATED:
                logger.debug("✅ Segment %s déjà validé.", seg.uid)
                valid_segments.append(seg)

        valid_count = len(valid_segments)
        logger.debug("🔍 Segments validés : %d", valid_count)
        # auto_valid = valid_count == total
        # logger.debug("🔍 Auto-validation : %s", auto_valid)

        # --- Si pas auto-validée : mise à jour simple ---
        if not valid_segments:
            return {
                "uid": video.uid,
                "valid": valid_count,
                "total": total,
                "moved": False,
            }

        # --- Auto-validation complète : tentative de déplacement ---
        mover = FileMover()

        # Plan des destinations (relatives)
        planned_targets = {}
        safe_name = sanitize(video.name)
        logger.debug("🔍 Nom sécurisé pour la vidéo : %s", safe_name)
        for seg in valid_segments:
            if not seg.filename_predicted:
                return {
                    "uid": video.uid,
                    "valid": valid_count,
                    "total": total,
                    "moved": False,
                }
            dst_final = CUTMIND_BASEDIR / safe_name / seg.filename_predicted
            dst_rel = dst_final
            planned_targets[seg.uid] = dst_rel
            logger.debug("🔍 Segment %s → Destination planifiée : %s", seg.uid, dst_rel)

        moved_ok = mover.move_video_files(video, planned_targets, logger)
        logger.debug("🔍 Résultat du déplacement des fichiers : %s", moved_ok)

        if not moved_ok:
            return {
                "uid": video.uid,
                "valid": valid_count,
                "total": total,
                "moved": False,
            }

        # --- Déplacement réussi : commit DB ---
        with repo.transaction():
            for seg in valid_segments:
                seg.output_path = str(planned_targets[seg.uid])
                logger.debug("🔍 Mise à jour du chemin de sortie pour le segment %s : %s", seg.uid, seg.output_path)
                repo.update_segment_validation(seg)

        remove_empty_dirs(root_path=OUTPUT_DIR_SC, logger=logger)

        return {
            "uid": video.uid,
            "valid": valid_count,
            "total": total,
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
