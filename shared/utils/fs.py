# shared/utils/fs.py

from pathlib import Path

from shared.utils.logger import LoggerProtocol, ensure_logger


def safe_file_check(path: Path, logger: LoggerProtocol | None = None) -> None:
    """
    Vérifie qu'un fichier est valide, lisible et non vide.

    Utilisable dans TOUT le projet.
    """
    logger = ensure_logger(logger, __name__)

    if not path.exists():
        logger.error("❌ Fichier introuvable : %s", path)
        raise RuntimeError(f"Fichier manquant : {path}")

    try:
        size = path.stat().st_size
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("❌ Impossible de lire stat() %s : %s", path, exc)
        raise RuntimeError(f"Échec stat() pour {path}") from exc

    if size == 0:
        logger.error("❌ Fichier vide (0 bytes) : %s", path)
        raise RuntimeError(f"Fichier vide : {path}")

    try:
        with open(path, "rb") as f:
            f.read(64)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("❌ Lecture impossible %s : %s", path, exc)
        raise RuntimeError(f"Lecture impossible : {path}") from exc

    logger.debug("🟢 Fichier valide : %s", path)
