"""Service de renommage manuel d'une vidéo CutMind."""

from __future__ import annotations

from db.repository import CutMindRepository
from shared.status_orchestrator.statuses import OrchestratorStatus
from shared.utils.logger import LoggerProtocol, ensure_logger


def perform_video_rename(
    video_id: int,
    new_name: str,
    repo: CutMindRepository,
    logger: LoggerProtocol | None = None,
) -> int:
    """
    Renomme une vidéo et programme le déplacement de tous ses segments.

    Le déplacement physique est laissé à l'orchestrateur CutMind via
    SEGMENT_TO_MOVE.

    Returns:
        Nombre de segments programmés pour déplacement.

    Raises:
        ValueError: Si le nouveau nom est vide.
        RuntimeError: Si la vidéo est introuvable.
    """
    logger = ensure_logger(logger, __name__)

    normalized_name = new_name.strip()
    if not normalized_name:
        raise ValueError(f"Impossible de renommer la vidéo {video_id}: nom vide.")

    video = repo.get_video_with_segments(video_id=video_id)
    if video is None:
        raise RuntimeError(f"Vidéo {video_id} introuvable.")

    old_name = video.name

    if normalized_name == old_name.strip():
        logger.debug(
            "Vidéo %s déjà nommée %r, aucun renommage nécessaire.",
            video_id,
            normalized_name,
        )
        return 0

    video.name = normalized_name
    repo.update_video_name(video)

    # On recharge volontairement après l'UPDATE.
    video = repo.get_video_with_segments(video_id=video_id)
    if video is None:
        raise RuntimeError(f"Impossible de recharger la vidéo {video_id} après renommage.")

    for segment in video.segments:
        segment.pipeline_target = OrchestratorStatus.SEGMENT_TO_MOVE
        repo.update_segment_validation(segment)

    segment_count = len(video.segments)

    logger.info(
        "✏️ Vidéo %s renommée %r -> %r | %d segments à déplacer.",
        video_id,
        old_name,
        normalized_name,
        segment_count,
    )

    return segment_count
