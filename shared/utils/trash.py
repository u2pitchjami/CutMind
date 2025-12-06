""" """

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger


def delete_files(path: Path, ext: str = "*.jpg") -> None:
    for file in Path(path).glob(ext):
        # logger.debug(f"🧹 Vérifié : {file.name}")
        try:
            file.unlink()
            # logger.debug(f"🧹 Supprimé : {file.name}")
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur inatendue lors de la suppression.",
                code=ErrCode.UNEXPECTED,
                ctx=get_step_ctx({"path": path, "file": file.name}),
            ) from exc


def move_to_trash(file_path: Path, trash_root: Path) -> Path:
    """
    Déplace un fichier vers la corbeille (trash/YYYY-MM-DD/).

    Renvoie le chemin final.
    Lève CutMindError en cas d'échec.
    """
    if not file_path.exists():
        raise CutMindError(
            "Fichier introuvable lors du move_to_trash.", code=ErrCode.FILE_ERROR, ctx={"file_path": str(file_path)}
        )

    try:
        date_dir = trash_root / datetime.now().strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)

        dest_path = date_dir / file_path.name
        shutil.move(str(file_path), dest_path)
        return dest_path

    except Exception as exc:  # pylint: disable=broad-except
        raise CutMindError(
            "Impossible de déplacer le fichier vers la corbeille.",
            code=ErrCode.FILE_ERROR,
            ctx=get_step_ctx({"file_path": str(file_path), "trash_root": str(trash_root)}),
        ) from exc


@with_child_logger
def purge_old_trash(trash_root: Path, days: int = 7, logger: LoggerProtocol | None = None) -> None:
    logger = ensure_logger(logger, __name__)
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
