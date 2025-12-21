""" """

from __future__ import annotations

from pathlib import Path
import shutil

from shared.executors.resolution_utils import fix_segment_resolution, is_resolution_accepted
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.config import TRASH_DIR
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger


@with_child_logger
def ensure_resolution(
    video_path: Path, input_res: tuple[int, int], cleanup: bool = True, logger: LoggerProtocol | None = None
) -> tuple[Path, tuple[int, int]]:
    """
    Vérifie si une vidéo est entrelacée et la désentrelace si nécessaire.

    Retourne le chemin à utiliser (inchangé ou nouveau).
    """
    logger = ensure_logger(logger, __name__)
    try:
        if is_resolution_accepted(input_res):
            logger.debug(f"✅ Résolution correcte : {video_path.name} - {input_res}")
            return video_path, input_res

        logger.info(f"⚙️ résolution incorrecte détectée : {video_path.name} - {input_res}")
        resize_path = video_path.with_name(f"{video_path.stem}_resize.mp4")
        logger.info(f"🧩 Resize en cours : {video_path.name} → {resize_path}")
        new_res = fix_segment_resolution(in_path=video_path, out_path=resize_path, input_res=input_res)
        if new_res:
            logger.info(f"✅ Vidéo resizée : {resize_path}")

            if cleanup:
                try:
                    shutil.move(video_path, TRASH_DIR / video_path.name)
                    logger.debug(f"🧹 Fichier original déplacé vers TRASH_DIR : {video_path.name}")
                except Exception as e:
                    logger.warning(f"⚠️ Impossible de déplacer {video_path.name} : {e}")

            return resize_path, new_res

        logger.warning("⚠️ Le Resize a échoué, utilisation du fichier original.")
        return video_path
    except CutMindError as err:
        raise err.with_context(get_step_ctx({"video_path": video_path, "cleanup": cleanup})) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors du resize de la vidéo.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video_path": str(video_path)}),
        ) from exc
