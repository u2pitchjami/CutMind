"""
cutmind/core/file_mover.py
Déplacement transactionnel (prepare → commit) sans interaction DB
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil

from cutmind.models.db_models import Video
from shared.utils.config import CUTMIND_BASEDIR
from shared.utils.logger import get_logger

logger = get_logger(__name__)


def sanitize(name: str) -> str:
    """
    Nettoie un nom de fichier (compatible Windows/Unix).
    """
    try:
        sanitized = re.sub(r'[<>:"/\\|?*]', " ", name)
        # sanitized = sanitized.replace(" ", "_")
        return sanitized
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("[sanitize_filename] erreur: %s", exc)
        return "file"


class FileMover:
    """Gère uniquement le déplacement des fichiers validés (sans mise à jour DB)."""

    def __init__(self) -> None:
        pass

    def move_video_files(self, video: Video, planned_targets: dict[str, Path]) -> bool:
        """
        Déplace les fichiers d'une vidéo selon les chemins planifiés.
        Utilise une stratégie prepare → commit :
          1. Copie vers fichiers temporaires .__moving__
          2. Fsync pour sécurité
          3. Rename atomique
          4. Suppression des sources
        Args:
            video: objet vidéo
            planned_targets: dict {segment_uid: Path(relative)}
        Returns:
            bool: True si succès, False sinon.
        """
        safe_name = sanitize(video.name)
        prepared = []  # liste (src_abs, dst_temp, dst_final)

        try:
            # --- Phase PREPARE ---
            for seg in video.segments:
                dst_rel = planned_targets.get(seg.uid)
                if not dst_rel:
                    continue

                if not seg.output_path:
                    raise ValueError(f"Segment sans chemin source : {seg.uid}")
                src_abs = Path(seg.output_path)
                dst_final = CUTMIND_BASEDIR / safe_name / Path(dst_rel).name
                dst_temp = dst_final.with_suffix(dst_final.suffix + ".__moving__")

                if not src_abs.exists():
                    raise FileNotFoundError(f"Segment introuvable : {src_abs}")

                dst_final.parent.mkdir(parents=True, exist_ok=True)
                logger.debug("⏳ Copie %s -> %s", src_abs, dst_temp)
                shutil.copy2(src_abs, dst_temp)
                with open(dst_temp, "rb") as tmpf:
                    os.fsync(tmpf.fileno())
                prepared.append((src_abs, dst_temp, dst_final))

            # --- Phase COMMIT ---
            for src_abs, dst_temp, dst_final in prepared:
                os.replace(dst_temp, dst_final)
                os.remove(src_abs)

            logger.info("✅ Déplacement réussi : %s (%d fichiers)", video.name, len(prepared))
            return True

        except Exception as err:
            logger.exception("❌ Échec déplacement vidéo %s : %s", video.name, err)
            self._cleanup(prepared)
            return False

    @staticmethod
    def safe_copy(src: Path, dst: Path) -> None:
        """
        Copie un fichier avec gestion des exceptions et logs.
        Écrase la destination si elle existe.
        """
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            logger.debug("📦 Copie réussie : %s → %s", src, dst)
        except FileNotFoundError:
            logger.error("❌ Fichier source introuvable : %s", src)
            raise
        except PermissionError:
            logger.error("⚠️ Permission refusée : %s → %s", src, dst)
            raise
        except Exception as err:
            logger.error("❌ Erreur copie %s → %s : %s", src, dst, err)
            raise

    @staticmethod
    def _cleanup(prepared: list[tuple[Path, Path, Path]]) -> None:
        """Nettoie les fichiers .__moving__ laissés après échec."""
        for _, dst_temp, _ in prepared:
            try:
                if dst_temp.exists():
                    dst_temp.unlink()
                    logger.debug("🧹 Fichier temporaire supprimé : %s", dst_temp)
            except Exception as cleanup_err:
                logger.warning("⚠️ Échec nettoyage %s : %s", dst_temp, cleanup_err)
