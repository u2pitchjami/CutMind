from __future__ import annotations

import os
from pathlib import Path
import re
import shutil

from cutmind.models_cm.db_models import Video
from shared.utils.config import CUTMIND_BASEDIR
from shared.utils.fs import safe_file_check
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger


@with_child_logger
def sanitize(name: str, logger: LoggerProtocol | None = None) -> str:
    logger = ensure_logger(logger, __name__)
    try:
        sanitized = re.sub(r'[<>:"/\\|?*]', " ", name)
        return sanitized
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("[sanitize_filename] erreur: %s", exc)
        return "file"


class FileMover:
    """Gère uniquement le déplacement des fichiers validés (sans mise à jour DB)."""

    def __init__(self) -> None:
        pass

    @with_child_logger
    def move_video_files(
        self, video: Video, planned_targets: dict[str, Path], logger: LoggerProtocol | None = None
    ) -> bool:
        logger = ensure_logger(logger, __name__)
        safe_name = sanitize(video.name, logger=logger)
        prepared = []

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

                # 🔥 Vérification source (anti-FUSE / anti-corruption)
                safe_file_check(src_abs, logger)

                dst_final.parent.mkdir(parents=True, exist_ok=True)
                logger.debug("⏳ Copie %s -> %s", src_abs, dst_temp)

                shutil.copy2(src_abs, dst_temp)

                with open(dst_temp, "rb") as tmpf:
                    os.fsync(tmpf.fileno())

                prepared.append((src_abs, dst_temp, dst_final))

            # --- Phase COMMIT ---
            for src_abs, dst_temp, dst_final in prepared:
                os.replace(dst_temp, dst_final)
                if src_abs.exists():
                    os.remove(src_abs)

            logger.info("✅ Déplacement réussi : %s (%d fichiers)", video.name, len(prepared))
            return True

        except Exception as err:
            logger.exception("❌ Échec déplacement vidéo %s : %s", video.name, err)
            self._cleanup(prepared, logger=logger)
            return False

    @staticmethod
    @with_child_logger
    def safe_copy(src: Path, dst: Path, logger: LoggerProtocol | None = None) -> None:
        logger = ensure_logger(logger, __name__)
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            logger.debug("📦 Copie réussie : %s → %s", src, dst)
        except Exception as err:  # pylint: disable=broad-except
            logger.error("❌ Erreur copie %s → %s : %s", src, dst, err)
            raise

    @staticmethod
    @with_child_logger
    def _cleanup(prepared: list[tuple[Path, Path, Path]], logger: LoggerProtocol | None = None) -> None:
        logger = ensure_logger(logger, __name__)
        for _, dst_temp, _ in prepared:
            try:
                if dst_temp.exists():
                    dst_temp.unlink()
                    logger.debug("🧹 Fichier temporaire supprimé : %s", dst_temp)
            except Exception as cleanup_err:
                logger.warning("⚠️ Échec nettoyage %s : %s", dst_temp, cleanup_err)

    @staticmethod
    @with_child_logger
    def safe_replace(src: Path, dst: Path, logger: LoggerProtocol | None = None) -> None:
        """
        Remplace un fichier même entre FS différents.
        Copie → fsync → rename atomique.
        """
        logger = ensure_logger(logger, __name__)

        # Vérification safe du fichier source
        from shared.utils.fs import safe_file_check

        safe_file_check(src, logger)

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = dst.with_suffix(dst.suffix + ".__moving__")

            # Copie sécurisée dans le temporaire
            FileMover.safe_copy(src, tmp_path, logger=logger)

            # Remplacement atomique
            os.replace(tmp_path, dst)

            # Suppression du fichier source
            if src.exists():
                os.remove(src)

            logger.info("✅ safe_replace: %s → %s", src, dst)

        except Exception as err:
            logger.error("❌ Erreur safe_replace %s → %s : %s", src, dst, err)
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
                    logger.debug("🧹 Temp supprimé : %s", tmp_path)
            except Exception as cleanup_err:
                logger.warning("⚠️ Échec cleanup %s : %s", tmp_path, cleanup_err)
            raise
