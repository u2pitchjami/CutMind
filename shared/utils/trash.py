""" """

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil

from shared.utils.logger import get_logger

logger = get_logger(__name__)


def delete_files(path: Path, ext: str = "*.jpg") -> None:
    for file in Path(path).glob(ext):
        # logger.debug(f"🧹 Vérifié : {file.name}")
        try:
            file.unlink()
            # logger.debug(f"🧹 Supprimé : {file.name}")
        except Exception as e:
            logger.warning(f"⚠️ Impossible de supprimer {file.name} : {e}")


def move_to_trash(file_path: Path, trash_root: Path) -> Path:
    """
    Déplace un fichier vers la corbeille (trash/YYYY-MM-DD/).
    """
    try:
        if not file_path.exists():
            logger.warning(f"⚠️ Fichier introuvable : {file_path}")
            return file_path

        date_dir = trash_root / datetime.now().strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)

        dest_path = date_dir / file_path.name
        shutil.move(str(file_path), dest_path)
        logger.info(f"🗑️ Fichier déplacé vers corbeille : {dest_path}")
        return dest_path

    except Exception as e:
        logger.error(f"❌ Impossible de déplacer {file_path} vers la corbeille : {e}")
        return file_path


def purge_old_trash(trash_root: Path, days: int = 7) -> None:
    now = datetime.now()
    for folder in trash_root.iterdir():
        if folder.is_dir():
            try:
                date = datetime.strptime(folder.name, "%Y-%m-%d")
                if (now - date).days > days:
                    shutil.rmtree(folder)
                    logger.info(f"🧹 Corbeille purgée : {folder}")
            except ValueError:
                continue
