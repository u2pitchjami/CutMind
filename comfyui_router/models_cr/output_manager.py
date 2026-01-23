from __future__ import annotations

from math import ceil
import os
from pathlib import Path
import time

from comfyui_router.executors.output import _is_stable
from comfyui_router.models_cr.videojob import VideoJob
from shared.utils.config import OUTPUT_DIR
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger


class OutputManager:
    """
    VERSION B++ (finale et robuste)

    🔥 Fonctionne même si :
    - ComfyUI ne génère pas un fichier par batch
    - la croissance du fichier est irrégulière
    - la vidéo n’a pas d’audio
    - ComfyUI plante silencieusement

    🔍 Logique :
    - On détecte la croissance du MP4 partiel.
    - Tant que la taille augmente → progression.
    - Quand la taille reste stable pendant stable_time → FIN.
    - Si audio présent → le fichier audio final fait foi.
    - Si freeze trop long → crash probable.
    """

    @with_child_logger
    def wait_for_output(
        self,
        video_job: VideoJob,
        expect_audio: bool | None = None,
        stable_time: int = 90,
        poll_interval: int = 5,
        timeout: int = 7200,
        logger: LoggerProtocol | None = None,
    ) -> Path | None:
        logger = ensure_logger(logger, __name__)

        filename_prefix = video_job.path.stem
        expect_audio = expect_audio if expect_audio is not None else video_job.has_audio

        # B++ utilise nb_frames_batch uniquement pour logs (plus obligatoire pour la logique)
        expected_batches = ceil(video_job.nb_frames / video_job.nb_frames_batch)

        logger.info(
            f"🎬 Attente du fichier final '{filename_prefix}' "
            f"(batches attendus ≈ {expected_batches}, audio={expect_audio})"
        )

        first_batch_detected = False
        start = time.time()
        video_file: Path | None = None

        last_size = 0
        last_growth_time = time.time()

        SIZE_DELTA_THRESHOLD = 1 * 1024 * 1024  # 5 MB : croissance significative
        logger.debug(f"SIZE_DELTA_THRESHOLD : {SIZE_DELTA_THRESHOLD}")
        FREEZE_TIME = max(stable_time * 3, 120)  # si aucune croissance pendant trop longtemps → crash suspect
        logger.debug(f"FREEZE_TIME : {FREEZE_TIME}")
        logger.debug(f"stable_time : {stable_time}")
        while time.time() - start < timeout:
            # ------------------------------------------
            # 1) Détection du fichier vidéo partiel
            # ------------------------------------------
            if video_file is None:
                matches = sorted(OUTPUT_DIR.glob(f"{filename_prefix}_*.mp4"))
                if matches:
                    video_file = matches[0]
                    # last_size = video_file.stat().st_size
                    last_growth_time = time.time()
                    logger.info(f"📹 Fichier détecté : {video_file.name}")

            if video_file is None:
                time.sleep(poll_interval)
                continue

            stat = os.stat(video_file)
            logger.debug(
                "size=%d mtime=%f",
                stat.st_size,
                stat.st_mtime,
            )
            # ------------------------------------------
            # 2) Analyse de la croissance du fichier
            # ------------------------------------------
            current_size = video_file.stat().st_size
            logger.debug(f"current_size : {current_size}")
            delta = current_size - last_size
            logger.debug(f"delta : {delta}")
            if first_batch_detected is False:
                batch1_time = last_growth_time - start
                logger.debug(f"batch1_time : {batch1_time}")
                FREEZE_TIME = min(max(int(batch1_time * 3), 120), 900)
                logger.debug(f"FREEZE_TIME : {FREEZE_TIME}")
                stable_time = min(max(int(batch1_time * 1.5), 30), 300)
                logger.debug(f"stable_time : {stable_time}")

                logger.info(f"⏱️ Premier batch détecté : {batch1_time:.2f}s")
                logger.info(f"⏳ Freeze time ajusté à {FREEZE_TIME}s, stable time à {stable_time}s")
                first_batch_detected = True

            # ------------------------------------------
            # 3) Vérification du fichier audio final
            # ------------------------------------------
            if expect_audio:
                if delta > SIZE_DELTA_THRESHOLD:
                    # Croissance visible → batch suspecté
                    growth_mb = delta / 1024 / 1024
                    logger.info(f"📈 Croissance détectée : +{growth_mb:.2f} MB")
                    last_size = current_size
                    logger.debug(f"last_size : {last_size}")
                    last_growth_time = time.time()
                    logger.debug(f"last_growth_time : {last_growth_time}")
                    audio_file = video_file.with_name(video_file.stem + "-audio.mp4")
                if audio_file.exists():
                    logger.info(f"🎧 Audio final détecté : {audio_file.name}")

                    if _is_stable(audio_file, 30, poll_interval):
                        logger.info("✅ Audio stable → workflow terminé")
                        video_job.output_file = audio_file
                        return audio_file

            # ------------------------------------------
            # 4) Pas d’audio → stabilisation de la vidéo
            # ------------------------------------------
            if not expect_audio:
                if _is_stable(video_file, stable_time, poll_interval):
                    logger.info("✅ Vidéo stable → workflow terminé")
                    video_job.output_file = video_file
                    return video_file
                logger.info(" Vidéo non stable")

            # ------------------------------------------
            # 5) Détection de freeze (ComfyUI planté)
            # ------------------------------------------
            if (time.time() - last_growth_time) > FREEZE_TIME:
                logger.error(
                    f"🛑 Freeze détecté : aucune croissance depuis {FREEZE_TIME}s (taille={current_size} bytes)"
                )
                # On considère que ComfyUI a planté → retour None
                return None

            time.sleep(poll_interval)

        # ------------------------------------------
        # Timeout
        # ------------------------------------------
        elapsed = time.time() - start
        logger.error(f"⏱️ Timeout après {elapsed:.1f}s — fichier final introuvable.")
        return None
