from __future__ import annotations

import os
from pathlib import Path
import re
import shutil

from cutmind.models_cm.db_models import Video
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.config import CUTMIND_BASEDIR
from shared.utils.fs import safe_file_check
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger


def sanitize(name: str) -> str:
    try:
        sanitized = re.sub(r'[<>:"/\\|?*]', " ", name)
        return sanitized
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors du sanitize.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"name": name}),
        ) from exc


class FileMover:
    """Gère uniquement le déplacement des fichiers validés (sans mise à jour DB)."""

    def __init__(self) -> None:
        pass

    @with_child_logger
    def move_video_files(
        self, video: Video, planned_targets: dict[str, Path], logger: LoggerProtocol | None = None
    ) -> bool:
        logger = ensure_logger(logger, __name__)
        safe_name = sanitize(video.name)
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
        except CutMindError as err:
            raise err.with_context(get_step_ctx({"video.name": video.name})) from err
        except Exception as err:
            self._cleanup(prepared)
            raise CutMindError(
                "❌ Échec déplacement vidéo.",
                code=ErrCode.UNEXPECTED,
                ctx=get_step_ctx({"video.name": video.name}),
            ) from err

    @staticmethod
    def safe_copy(src: Path, dst: Path) -> None:
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        except Exception as err:
            raise CutMindError(
                "❌ Échec déplacement vidéo.",
                code=ErrCode.UNEXPECTED,
                ctx=get_step_ctx({"src": src, "dst": dst}),
            ) from err

    @staticmethod
    def _cleanup(prepared: list[tuple[Path, Path, Path]]) -> None:
        for _, dst_temp, _ in prepared:
            try:
                if dst_temp.exists():
                    dst_temp.unlink()
            except Exception as err:
                raise CutMindError(
                    "❌ Échec nettoyage après échec déplacement.",
                    code=ErrCode.UNEXPECTED,
                    ctx=get_step_ctx({"dst_temp": dst_temp}),
                ) from err

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

        safe_file_check(src, logger=logger)

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = dst.with_suffix(dst.suffix + ".__moving__")

            # Copie sécurisée dans le temporaire
            FileMover.safe_copy(src, tmp_path)

            # Remplacement atomique
            os.replace(tmp_path, dst)

            # Suppression du fichier source
            if src.exists():
                os.remove(src)

        except Exception:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception as err:
                raise CutMindError(
                    "❌ Échec cleanup.",
                    code=ErrCode.UNEXPECTED,
                    ctx=get_step_ctx({"tmp_path": tmp_path}),
                ) from err
