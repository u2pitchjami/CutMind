""" """

from __future__ import annotations

from pathlib import Path

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.config import (
    INPUT_DIR,
    OUTPUT_DIR,
    TEMP_AUDIO_DIR,
    TEMP_FRAMES_INPUT_DIR,
    TEMP_FRAMES_RIFE_DIR,
    TEMP_FRAMES_UPSCALED_DIR,
    TRASH_DIR,
)
from shared.utils.logger import LoggerProtocol, ensure_logger
from shared.utils.settings import get_settings
from shared.utils.trash import cleanup_processing_dirs, move_to_trash, purge_old_trash


def cleanup_enhanced_dirs(
    logger: LoggerProtocol | None = None,
) -> None:
    """
    Nettoie les répertoires d'import et d'export de ComfyUI Router.
    - Supprime les fichiers temporaires plus anciens que la durée de rétention configurée.
    - Déplace les fichiers restants vers la corbeille.
    """
    logger = ensure_logger(logger, __name__)
    settings = get_settings()
    PURGE_DAYS = settings.router_processor.purge_days
    KEEP_TEMP_FILES = settings.router_processor.keep_temp_files

    files_deleted = 0
    directories_deleted = 0
    files_to_trash = 0
    directories_to_trash = 0
    processing_dirs = [
        TEMP_AUDIO_DIR,
        TEMP_FRAMES_INPUT_DIR,
        TEMP_FRAMES_RIFE_DIR,
        TEMP_FRAMES_UPSCALED_DIR,
    ]
    try:
        files_deleted, directories_deleted = cleanup_processing_dirs(
            processing_dirs,
            KEEP_TEMP_FILES,
            logger,
        )
        logger.info("🚚  %d fichiers temporaires supprimés.", files_deleted)
        logger.info("🚚  %d dossiers temporaires supprimés.", directories_deleted)

        for folder in (OUTPUT_DIR, INPUT_DIR):
            root = Path(folder)

            if not root.exists():
                continue

            for item in root.iterdir():
                move_to_trash(item, TRASH_DIR)

                if item.is_dir():
                    directories_to_trash += 1
                else:
                    files_to_trash += 1

        logger.info(
            "Corbeille : %s fichiers, %s dossiers déplacés vers la corbeille.",
            files_to_trash,
            directories_to_trash,
        )

        purge_old_trash(trash_root=TRASH_DIR, days=PURGE_DAYS, logger=logger)
        logger.info("🧹 Nettoyage des fichiers intermédiaires terminé")
        return

    except CutMindError:
        raise
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur innatendue Enhancer.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({}),
        ) from exc
