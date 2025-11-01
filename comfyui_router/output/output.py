""" """

from __future__ import annotations

from pathlib import Path
import time

from shared.utils.config import OUTPUT_DIR
from shared.utils.logger import get_logger

logger = get_logger(__name__)


def wait_for_output_v2(
    filename_prefix: str,
    expect_audio: bool = False,
    stable_time: int = 150,
    check_interval: int = 10,
    timeout: int = 7200,
) -> Path | None:
    """
    🧠 Surveillance optimisée des fichiers de sortie ComfyUI avec log de durée.
    """
    start_time = time.time()
    logger.debug(f"🕰 Début de la surveillance '{start_time}'")
    video_file: Path | None = None
    audio_file: Path | None = None

    logger.info(f"🎬 Attente des sorties pour '{filename_prefix}' (audio attendu = {expect_audio})")

    while time.time() - start_time < timeout:
        logger.debug(f"🕰 Intervalle de surveillance '{time.time()}'")
        logger.debug(f"📹 Fichier vidéo : {video_file if video_file else 'None'}")
        logger.debug(f"🎧 Fichier audio : {audio_file if audio_file else 'None'}")

        if video_file is None:
            matches = sorted(OUTPUT_DIR.glob(f"{filename_prefix}_*.mp4"))
            if matches:
                video_file = matches[0]
                logger.debug(f"📹 Fichier vidéo détecté : {video_file.name}")

        if expect_audio and video_file:
            candidate_audio = video_file.with_name(video_file.stem + "-audio.mp4")
            if candidate_audio.exists():
                audio_file = candidate_audio
                logger.debug(f"🎧 Fichier audio détecté : {audio_file.name}")

        if expect_audio and audio_file:
            if _is_stable(audio_file, stable_time, check_interval):
                elapsed = time.time() - start_time
                logger.info(f"✅ Fichier audio final stable : {audio_file.name} (⏱ {elapsed:.1f}s)")
                return audio_file

        elif not expect_audio and video_file:
            if _is_stable(video_file, stable_time, check_interval):
                elapsed = time.time() - start_time
                logger.info(f"✅ Fichier vidéo stable : {video_file.name} (⏱ {elapsed:.1f}s)")
                return video_file

        time.sleep(check_interval)

    elapsed = time.time() - start_time
    logger.warning(f"⏱️ Timeout atteint après {elapsed:.1f}s, aucun fichier final détecté.")
    return None


def _is_stable(path: Path, stable_time: int, check_interval: int) -> bool:
    """
    Vérifie que la taille d'un fichier reste stable pendant un certain temps.
    """
    last_size = -1
    stable_duration = 0

    while stable_duration < stable_time:
        if not path.exists():
            return False

        current_size = path.stat().st_size
        if current_size == last_size:
            stable_duration += check_interval
        else:
            stable_duration = 0
            last_size = current_size

        time.sleep(check_interval)

    return True


def cleanup_outputs(base_stem: str, keep: Path, output_dir: Path) -> None:
    """
    Supprime les fichiers intermédiaires de ComfyUI (png, mp4 sans audio, etc.) sauf le fichier final.
    """
    patterns = [
        f"{base_stem}_*.png",
        f"{base_stem}_*.mp4",
    ]

    for pattern in patterns:
        for file in output_dir.glob(pattern):
            logger.debug(f"🧹 Vérifié : {file.name}")
            if file.resolve() != keep.resolve():
                try:
                    file.unlink()
                    logger.debug(f"🧹 Supprimé : {file.name}")
                except Exception as e:
                    logger.warning(f"⚠️ Impossible de supprimer {file.name} : {e}")
