""" """

from __future__ import annotations

from pathlib import Path
import time

from comfyui_router.executors.output import _is_stable
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.config import OUTPUT_DIR
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger


@with_child_logger
def wait_for_output_v2(
    filename_prefix: str,
    expect_audio: bool = False,
    stable_time: int = 150,
    check_interval: int = 10,
    timeout: int = 7200,
    logger: LoggerProtocol | None = None,
) -> Path | None:
    """
    🧠 Surveillance optimisée des fichiers de sortie ComfyUI avec log de durée.
    """
    logger = ensure_logger(logger, __name__)
    try:
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
                    elapsed = time.time() - start_time
                    logger.info(f"✅ Fichier audio final stable : {audio_file.name} (⏱ {elapsed:.1f}s)")
                    return audio_file

            # if expect_audio and audio_file:
            #     if _is_stable(audio_file, stable_time, check_interval):
            #         elapsed = time.time() - start_time
            #         logger.info(f"✅ Fichier audio final stable : {audio_file.name} (⏱ {elapsed:.1f}s)")
            #         return audio_file

            elif not expect_audio and video_file:
                if _is_stable(video_file, stable_time, check_interval):
                    elapsed = time.time() - start_time
                    logger.info(f"✅ Fichier vidéo stable : {video_file.name} (⏱ {elapsed:.1f}s)")
                    return video_file

            time.sleep(check_interval)

        elapsed = time.time() - start_time
        logger.warning(f"⏱️ Timeout atteint après {elapsed:.1f}s, aucun fichier final détecté.")
        return None
    except CutMindError as err:
        raise err.with_context(
            get_step_ctx({"filename_prefix": filename_prefix, "expect_audio": expect_audio})
        ) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors du wait for output.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"filename_prefix": filename_prefix, "expect_audio": expect_audio}),
        ) from exc
