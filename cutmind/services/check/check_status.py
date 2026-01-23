# check/check_status.py

from __future__ import annotations

from collections.abc import Iterable

from cutmind.db.repository import CutMindRepository
from cutmind.models_cm.db_models import Video
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.status_orchestrator.statuses import SegmentStatus, VideoStatus
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from shared.utils.settings import SegmentStatusRule, VideoStatusRule, get_settings


def _match_all(values: Iterable[str], allowed: set[str]) -> bool:
    return all(v in allowed for v in values)


def _match_any(values: Iterable[str], allowed: set[str]) -> bool:
    return any(v in allowed for v in values)


def rule_matches_segments(
    rule: SegmentStatusRule,
    segment_statuses: list[str],
) -> bool:
    """
    Vérifie si une règle segments (V2) est satisfaite.
    """
    # expected : aucun segment ne doit exister
    if rule.expected is not None:
        return not segment_statuses

    # allowed : aucun segment hors liste
    if rule.allowed is not None:
        allowed = set(rule.allowed)
        if any(status not in allowed for status in segment_statuses):
            return False

    # all : tous les segments doivent matcher
    if rule.all is not None:
        allowed = set(rule.all)
        if not _match_all(segment_statuses, allowed):
            return False

    # any : au moins un segment doit matcher
    if rule.any is not None:
        allowed = set(rule.any)
        if not _match_any(segment_statuses, allowed):
            return False

    return True


def compute_video_status(video: Video) -> VideoStatus:
    """
    Calcule le statut vidéo à partir des segments (V2).
    - aucune IO
    - aucune écriture
    - aucune règle YAML
    """

    segments = video.segments
    if not segments:
        return VideoStatus.INIT

    # 1️⃣ Blocage humain CUT
    if any(s.pipeline_target == "CUT_VALIDATION" for s in segments):
        return VideoStatus.IN_CUT_VALIDATION

    # 2️⃣ Blocage humain FINAL
    if any(s.pipeline_target == "VALIDATION" for s in segments):
        return VideoStatus.IN_FINAL_VALIDATION

    # 3️⃣ Déplacement fichiers post-cut
    if any(s.pipeline_target == "TO_MOVE" for s in segments):
        return VideoStatus.POST_CUT_MOVE

    # 3️⃣ Rework IA demandé
    if any(s.pipeline_target == "IA" for s in segments):
        return VideoStatus.READY_FOR_IA

    # 4️⃣ Tous validés → fin
    if all(s.status == SegmentStatus.VALIDATED for s in segments):
        return VideoStatus.VALIDATED

    # 5️⃣ Enhancement
    if any(s.status == SegmentStatus.CUT_VALIDATED for s in segments):
        return VideoStatus.READY_FOR_ENHANCEMENT

    # 6️⃣ IA
    if any(s.status == SegmentStatus.ENHANCED for s in segments):
        return VideoStatus.READY_FOR_IA

    # 7️⃣ Confidence
    if any(s.status == SegmentStatus.IA_DONE for s in segments):
        return VideoStatus.READY_FOR_CONFIDENCE

    return VideoStatus.INIT


@with_child_logger
def check_video_segment_status(
    video_status: str,
    rule: VideoStatusRule,
    logger: LoggerProtocol | None = None,
) -> None:
    """
    Vérifie la cohérence entre un statut vidéo et les statuts de ses segments
    selon les règles V2.
    """
    logger = ensure_logger(logger, __name__)
    repo = CutMindRepository()

    try:
        segments = repo.get_segments_by_video_status(video_status)
        segment_statuses = [s["segment_status"] for s in segments]

        if rule_matches_segments(rule.segments, segment_statuses):
            logger.info("✅ Vidéo '%s' : cohérence OK.", video_status)
        else:
            logger.warning(
                "⚠️ Vidéo '%s' : incohérence segments=%s | règle=%s",
                video_status,
                segment_statuses,
                rule.segments,
            )

    except CutMindError as err:
        raise err.with_context(get_step_ctx({"video_status": video_status})) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur lors du check de cohérence vidéo/segments (V2).",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video_status": video_status}),
            original_exception=exc,
        ) from exc


@with_child_logger
def check_all_video_segment_status_rules(
    logger: LoggerProtocol | None = None,
) -> None:
    """
    Exécute toutes les règles V2 définies dans les settings CutMind.
    """
    logger = ensure_logger(logger, __name__)

    try:
        settings = get_settings()
        rules = settings.cutmind_status_consistency.rules

        for video_status, rule in rules.items():
            check_video_segment_status(
                video_status=video_status,
                rule=rule,
                logger=logger,
            )

    except CutMindError as err:
        raise err.with_context(get_step_ctx()) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur lors de l'exécution des checks V2.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx(),
            original_exception=exc,
        ) from exc
