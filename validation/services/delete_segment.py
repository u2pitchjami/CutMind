"""Service de suppression manuelle d'un segment CutMind."""

from __future__ import annotations

from pathlib import Path

from db.repository import CutMindRepository
from shared.utils.config import TRASH_DIR_SC
from shared.utils.logger import LoggerProtocol, ensure_logger
from shared.utils.trash import move_to_trash


def perform_segment_delete(
    segment_id: int,
    output_path: str | None,
    repo: CutMindRepository,
    logger: LoggerProtocol | None = None,
) -> None:
    """Déplace le fichier vers la corbeille puis supprime le segment en BDD."""
    logger = ensure_logger(logger, __name__)

    if output_path:
        file_path = Path(output_path)

        if file_path.exists():
            move_to_trash(
                file_path=file_path,
                trash_root=TRASH_DIR_SC,
            )
        else:
            logger.warning(
                "⚠️ Fichier du segment %s introuvable : %s",
                segment_id,
                file_path,
            )

    repo.delete_segment(segment_id)

    logger.info(
        "🗑️ Segment %s supprimé.",
        segment_id,
    )
