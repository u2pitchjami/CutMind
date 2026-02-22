""" """

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil

import cv2

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx


def get_downscale_factor(video_path: str) -> int:
    """Détermine dynamiquement le facteur de downscale selon la hauteur vidéo."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return 1  # fallback sans erreur
    height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    cap.release()

    if height >= 2160:  # 4K
        return 2  # vers 1080p
    elif height >= 1440:
        return 2
    elif height >= 1080:
        return 1
    else:
        return 1


def move_to_error(file_path: Path, error_root: Path) -> Path:
    """
    Déplace un fichier vers la corbeille (trash/YYYY-MM-DD/).
    """
    try:
        date_dir = error_root / datetime.now().strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)

        dest_path = date_dir / file_path.name
        shutil.move(str(file_path), dest_path)
        return dest_path

    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors du déplacement vers Error.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"file_path": str(file_path), "error_root": error_root}),
        ) from exc
        return file_path
