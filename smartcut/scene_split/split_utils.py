""" """

from __future__ import annotations

import csv
from datetime import datetime
import os
from pathlib import Path
import shutil

from shared.utils.config import OUPUT_DIR_SC
from shared.utils.logger import get_logger

logger = get_logger(__name__)


def move_to_error(file_path: Path, error_root: Path) -> Path:
    """
    Déplace un fichier vers la corbeille (trash/YYYY-MM-DD/).
    """
    try:
        if not file_path.exists():
            logger.warning(f"⚠️ Fichier introuvable : {file_path}")
            return file_path

        date_dir = error_root / datetime.now().strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)

        dest_path = date_dir / file_path.name
        shutil.move(str(file_path), dest_path)
        logger.info(f"🗑️ Fichier déplacé vers le dossier Error : {dest_path}")
        return dest_path

    except Exception as e:
        logger.error(f"❌ Impossible de déplacer {file_path} vers le dossier Error : {e}")
        return file_path


# ==========================================================
#  Sauvegarde segments (CSV)
# ==========================================================
def export_segments_csv(video_path: str, segments: list[tuple[float, float]]) -> None:
    """
    Sauvegarde les segments dans un CSV pour vérification.
    """
    out_path = Path(f"{OUPUT_DIR_SC}/{Path(video_path).stem}_segments.csv")
    os.makedirs(out_path.parent, exist_ok=True)
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["index", "start_s", "end_s", "duration_s"])
        for i, (s, e) in enumerate(segments, 1):
            writer.writerow([i, round(s, 3), round(e, 3), round(e - s, 3)])
    logger.info(f"💾 Segments sauvegardés dans {out_path}")
