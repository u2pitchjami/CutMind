""" """

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from shared.ffmpeg.ffmpeg_utils import detect_nvenc_available
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger


@with_child_logger
def get_total_frames(video_path: Path, logger: LoggerProtocol | None = None) -> int:
    """
    Retourne le nombre total de frames d'une vidéo via ffprobe.
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
            "stream=nb_frames,avg_frame_rate,duration",
            "-of",
            "json",
            str(video_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        stream = data.get("streams", [{}])[0]

        # Si nb_frames est directement disponible
        if "nb_frames" in stream and stream["nb_frames"].isdigit():
            return int(stream["nb_frames"])

        # Sinon, on estime via duration * avg_frame_rate
        if "duration" in stream and "avg_frame_rate" in stream:
            rate_num, rate_den = map(int, stream["avg_frame_rate"].split("/"))
            duration = float(stream["duration"])
            return int(duration * (rate_num / rate_den))

        logger.warning("Impossible de déterminer le nombre de frames pour %s", video_path)
        return 0

    except subprocess.CalledProcessError as err:
        logger.error("Erreur FFprobe: %s", err)
        return 0
    except Exception as exc:
        logger.error("Erreur inattendue: %s", exc)
        return 0


@with_child_logger
def video_has_audio(video_path: Path, logger: LoggerProtocol | None = None) -> bool:
    """
    Retourne True si la vidéo contient une piste audio (via ffprobe).
    """
    logger = ensure_logger(logger, __name__)
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=index",
                "-of",
                "csv=p=0",
                str(video_path),
            ],
            capture_output=True,
            text=True,
        )
        return bool(result.stdout.strip())
    except Exception as e:
        logger.error(f"⚠️ Erreur ffprobe : {e}")
        return False


@with_child_logger
def convert_to_60fps(input_path: Path, output_path: Path, logger: LoggerProtocol | None = None) -> bool:
    """
    Convertit une vidéo à 60 FPS en H.265, avec détection auto GPU/CPU.

    - Utilise hevc_nvenc (GPU) si disponible, sinon libx265 (CPU)
    - GPU : mode CQ (qualité constante)
    - CPU : mode CRF (qualité constante)
    """
    logger = ensure_logger(logger, __name__)
    use_nvenc = detect_nvenc_available(logger=logger)

    # Sélection des paramètres selon le mode
    if use_nvenc:
        codec = "hevc_nvenc"
        preset = "p6"
        quality_args = ["-cq", "17", "-rc", "vbr", "-b:v", "0"]
        hwaccel = ["-hwaccel", "cuda"]
        logger.info("🚀 NVENC détecté — encodage GPU (hevc_nvenc) activé.")
    else:
        codec = "libx265"
        preset = "slow"
        quality_args = ["-crf", "17"]
        hwaccel = []
        logger.info("⚙️ NVENC non disponible — encodage CPU (libx265).")

    cmd = [
        "ffmpeg",
        "-y",  # overwrite sans confirmation
        *hwaccel,
        "-i",
        str(input_path),
        "-r",
        "60",
        "-c:v",
        codec,
        "-preset",
        preset,
        *quality_args,
        "-c:a",
        "copy",
        str(output_path),
    ]

    # Log propre de la commande pour debug
    logger.debug("🧩 Commande FFmpeg : " + " ".join(cmd))

    try:
        subprocess.run(cmd, check=True)
        logger.info(f"✅ Conversion 60 FPS terminée : {output_path.name}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Échec de la conversion : {e}")
        return False
