""" """

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil

from shared.utils.config import OUPUT_DIR_SC
from shared.utils.logger import get_logger
from smartcut.models_sc.lite_session import SmartCutLiteSession

logger = get_logger(__name__)


def relocate_and_rename_segments(session: SmartCutLiteSession, output_dir: Path = OUPUT_DIR_SC) -> None:
    """
    Renomme et déplace tous les segments dans le dossier de sortie.
    """
    output_dir = output_dir / Path(session.dir_path.name)
    output_dir.mkdir(parents=True, exist_ok=True)
    for _, seg in enumerate(session.segments, start=1):
        try:
            # Vérifie la source
            src = Path(seg.output_path or seg.filename_predicted or "")
            if not src.exists():
                logger.warning(f"⚠️ Fichier manquant : {src}")
                continue

            # Nouveau nom prédictif
            seg.filename_predicted = f"seg_{seg.id:04d}_{seg.uid}.mp4"
            seg.output_path = str(output_dir / seg.filename_predicted)
            dest = Path(seg.output_path)

            # Déplacement
            shutil.move(str(src), str(dest))
            logger.info(f"📦 Déplacé : {src.name} → {dest}")

            # Mise à jour du segment
            seg.last_updated = datetime.now().isoformat()
            session.save(session.state_path)

        except Exception as e:
            logger.error(f"❌ Erreur déplacement segment {seg.uid} : {e}")
            seg.error = str(e)

    # Sauvegarde mise à jour
    session.save(session.state_path)
    logger.info(f"✅ Tous les segments ont été déplacés vers {output_dir}")
