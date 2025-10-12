from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

from comfyui_router.utils.config import TRASH_DIR
from comfyui_router.utils.logger import get_logger

logger = get_logger("Comfyui Router")


def is_interlaced(video_path: Path) -> bool:
    """Retourne True si la vidéo est entrelacée."""
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


def deinterlace_video(input_path: Path, output_path: Path, use_cuda: bool = False) -> bool:
    """Désentrelace une vidéo (CPU ou GPU selon l’option)."""
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


def ensure_deinterlaced(video_path: Path, use_cuda: bool = True, cleanup: bool = True) -> Path:
    """
    Vérifie si une vidéo est entrelacée et la désentrelace si nécessaire.
    Retourne le chemin à utiliser (inchangé ou nouveau).
    """
    if not is_interlaced(video_path):
        logger.debug(f"✅ Vidéo progressive : {video_path.name}")
        return video_path

    logger.info(f"⚙️ Vidéo entrelacée détectée : {video_path.name}")
    deint_path = video_path.with_name(f"{video_path.stem}_deint.mp4")

    if deinterlace_video(video_path, deint_path, use_cuda=use_cuda):
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


def video_has_audio(video_path: Path) -> bool:
    """Retourne True si la vidéo contient une piste audio (via ffprobe)."""
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
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return bool(result.stdout.strip())
    except Exception as e:
        logger.error(f"⚠️ Erreur ffprobe : {e}")
        return False


def get_resolution(filepath: Path) -> tuple[int, int]:
    """Retourne la largeur et hauteur de la vidéo via ffprobe."""
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(filepath),
        ]
        result = subprocess.check_output(cmd)
        info = json.loads(result)
        w = info["streams"][0]["width"]
        h = info["streams"][0]["height"]
        return w, h
    except Exception:
        return 0, 0


def get_fps(filepath: Path) -> float:
    """Retourne le framerate de la vidéo."""
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=r_frame_rate",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(filepath),
        ]
        output = subprocess.check_output(cmd).decode().strip()
        num, den = map(int, output.split("/"))
        return num / den if den else float(num)
    except Exception:
        return 0.0


def detect_nvenc_available() -> bool:
    """
    Vérifie si l'encodeur NVIDIA NVENC (hevc_nvenc) est disponible.
    """
    try:
        result = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, check=True)
        return "hevc_nvenc" in result.stdout
    except subprocess.CalledProcessError:
        logger.warning("⚠️ Impossible de détecter les encodeurs FFmpeg.")
        return False


def convert_to_60fps(input_path: Path, output_path: Path) -> bool:
    """
    Convertit une vidéo à 60 FPS en H.265, avec détection auto GPU/CPU.

    - Utilise hevc_nvenc (GPU) si disponible, sinon libx265 (CPU)
    - GPU : mode CQ (qualité constante)
    - CPU : mode CRF (qualité constante)
    """
    use_nvenc = detect_nvenc_available()

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
