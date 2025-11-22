""" """

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from shared.utils.config import TRASH_DIR
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger


@with_child_logger
def is_interlaced(video_path: Path, logger: LoggerProtocol | None = None) -> bool:
    """
    Retourne True si la vidéo est entrelacée.
    """
    logger = ensure_logger(logger, __name__)
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=field_order",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        field_order = result.stdout.strip().lower()
        logger.debug(f"Analyse entrelacement ({video_path.name}) → {field_order or 'inconnu'}")
        return field_order not in ("progressive", "", "unknown")
    except subprocess.CalledProcessError as e:
        logger.warning(f"⚠️ Impossible de détecter l'entrelacement ({video_path.name}) : {e}")
        return False


@with_child_logger
def deinterlace_video(
    input_path: Path, output_path: Path, use_cuda: bool = False, logger: LoggerProtocol | None = None
) -> bool:
    """
    Désentrelace une vidéo (CPU ou GPU selon l’option).
    """
    logger = ensure_logger(logger, __name__)
    try:
        filter_type = "yadif_cuda" if use_cuda else "yadif"
        codec = "hevc_nvenc" if use_cuda else "libx265"
        cmd = [
            "ffmpeg",
            "-y",
            "-hwaccel",
            "cuda" if use_cuda else "auto",
            "-i",
            str(input_path),
            "-vf",
            filter_type,
            "-c:v",
            codec,
            "-preset",
            "slow",
            "-crf",
            "17",
            "-c:a",
            "copy",
            str(output_path),
        ]
        logger.info(f"🧩 Désentrelacement en cours : {input_path.name} → {output_path.name}")
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Échec du désentrelacement : {e}")
        return False


@with_child_logger
def ensure_deinterlaced(
    video_path: Path, use_cuda: bool = True, cleanup: bool = True, logger: LoggerProtocol | None = None
) -> Path:
    """
    Vérifie si une vidéo est entrelacée et la désentrelace si nécessaire.

    Retourne le chemin à utiliser (inchangé ou nouveau).
    """
    logger = ensure_logger(logger, __name__)
    if not is_interlaced(video_path, logger=logger):
        logger.debug(f"✅ Vidéo progressive : {video_path.name}")
        return video_path

    logger.info(f"⚙️ Vidéo entrelacée détectée : {video_path.name}")
    deint_path = video_path.with_name(f"{video_path.stem}_deint.mp4")

    if deinterlace_video(video_path, deint_path, use_cuda=use_cuda, logger=logger):
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
