""" """

from __future__ import annotations

from pathlib import Path
import shutil

from shared.executors.deinterlace import deinterlace_video, is_interlaced
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.config import TRASH_DIR
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger


@with_child_logger
def ensure_deinterlaced(
    video_path: Path, use_cuda: bool = True, cleanup: bool = True, logger: LoggerProtocol | None = None
) -> Path:
    """
    Vérifie si une vidéo est entrelacée et la désentrelace si nécessaire.

    Retourne le chemin à utiliser (inchangé ou nouveau).
    """
    logger = ensure_logger(logger, __name__)
    try:
        field_order = is_interlaced(video_path)
        logger.debug(f"Analyse entrelacement ({video_path.name}) → {field_order or 'inconnu'}")
        if field_order in ("progressive"):
            logger.debug(f"✅ Vidéo progressive : {video_path.name}")
            return video_path

        logger.info(f"⚙️ Vidéo entrelacée détectée : {video_path.name}")
        deint_path = video_path.with_name(f"{video_path.stem}_deint.mp4")
        logger.info(f"🧩 Désentrelacement en cours : {video_path.name} → {deint_path.name}")
        if deinterlace_video(video_path, deint_path):
            logger.info(f"✅ Vidéo désentrelacée : {deint_path.name}")

            if cleanup:
                try:
                    shutil.move(video_path, TRASH_DIR / video_path.name)
                    logger.debug(f"🧹 Fichier original déplacé vers TRASH_DIR : {video_path.name}")
                except Exception as e:
                    logger.warning(f"⚠️ Impossible de déplacer {video_path.name} : {e}")

            return deint_path

        logger.warning("⚠️ Le désentrelacement a échoué, utilisation du fichier original.")
        return video_path
    except CutMindError as err:
        raise err.with_context(
            get_step_ctx({"video_path": video_path, "cleanup": cleanup, "use_cuda": use_cuda})
        ) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors du deinterlace de la vidéo.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video_path": str(video_path)}),
            original_exception=exc,
        ) from exc
