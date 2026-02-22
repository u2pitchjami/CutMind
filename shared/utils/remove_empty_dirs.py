import os
from pathlib import Path

from shared.utils.logger import LoggerProtocol, ensure_logger


def remove_empty_dirs(root_path: str | Path, dry_run: bool = False, logger: LoggerProtocol | None = None) -> int:
    """
    Supprime récursivement les sous-dossiers vides dans un dossier donné.

    Args:
        root_path (str | Path): chemin racine à scanner
        dry_run (bool): si True, ne supprime pas, affiche seulement ce qui serait supprimé

    Returns:
        int: nombre de dossiers supprimés
    """
    logger = ensure_logger(logger, __name__)
    root = Path(root_path).resolve()
    if not root.exists() or not root.is_dir():
        logger.warning("🚫 Le chemin %s n'existe pas ou n'est pas un dossier.", root)
        return 0

    deleted_count = 0

    # On parcourt de la profondeur max vers la racine
    for dirpath, _dirnames, _filenames in os.walk(root, topdown=False):
        dir_path = Path(dirpath)

        # On ignore le dossier racine
        if dir_path == root:
            continue

        # Vérifie si le dossier est vide
        if not any(Path(dir_path).iterdir()):
            if dry_run:
                logger.info("🧹 [DryRun] Dossier vide trouvé : %s", dir_path)
            else:
                try:
                    dir_path.rmdir()
                    deleted_count += 1
                    logger.info("🧹 Dossier vide supprimé : %s", dir_path)
                except Exception as e:
                    logger.error("❌ Erreur suppression %s : %s", dir_path, e)

    logger.info("✅ %d dossiers vides supprimés dans %s", deleted_count, root)
    return deleted_count
