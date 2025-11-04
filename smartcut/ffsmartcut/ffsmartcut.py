"""
Commandes ffmpeg pour smartcut.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import subprocess

import ffmpeg  # type: ignore

from shared.models.config_manager import CONFIG
from shared.utils.config import SAFE_FORMATS
from shared.utils.logger import get_logger
from smartcut.models_sc.smartcut_model import SmartCutSession

logger = get_logger(__name__)

PRESET = CONFIG.smartcut["ffsmartcut"]["preset"]
RC = CONFIG.smartcut["ffsmartcut"]["rc"]
CQ = CONFIG.smartcut["ffsmartcut"]["cq"]
PIX_FMT = CONFIG.smartcut["ffsmartcut"]["pix_fmt"]
VCODEC = CONFIG.smartcut["ffsmartcut"]["vcodec"]

# ========== Utils FFprobe/FFmpeg ==========


def get_duration(video_path: Path) -> float:
    """
    Retourne la durée en secondes (0.0 si échec).
    """
    cmd: list[str] = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    try:
        out = subprocess.check_output(cmd).decode().strip()
        return float(out)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("ffprobe duration error: %s", exc)
        return 0.0


def cut_video(
    video_path: Path,
    start: float,
    end: float,
    out_dir: Path,
    index: int,
    keywords: str,
    use_cuda: bool = False,
    vcodec_cpu: str = "libx265",
    vcodec_gpu: str = "hevc_nvenc",
    crf: int = 18,
    preset_cpu: str = "slow",
    preset_gpu: str = "p7",
    session: SmartCutSession | None = None,  # 🧠 session SmartCut (optionnelle)
    state_path: Path | None = None,  # 💾 JSON à mettre à jour
) -> Path | None:
    """
    Effectue la découpe réelle (encode CPU/GPU) et met à jour la session SmartCut.
    """
    codec = vcodec_gpu if use_cuda else vcodec_cpu
    preset = preset_gpu if use_cuda else preset_cpu
    hwaccel = "cuda" if use_cuda else "auto"

    seg = None
    if session:
        seg = next((s for s in session.segments if s.id == index), None)
        if seg:
            seg.predict_filename(out_dir)
            if seg.output_path is None:
                raise ValueError("Segment output_path non défini avant conversion en Path")
            out_path = Path(seg.output_path)
            out_name = seg.filename_predicted
        else:
            out_name = f"seg_{index:04d}_unknown.mp4"
            out_path = out_dir / out_name
    else:
        out_name = f"seg_{index:04d}_standalone.mp4"
        out_path = out_dir / out_name

    cmd: list[str] = [
        "ffmpeg",
        "-y",
        "-hwaccel",
        hwaccel,
        "-i",
        str(video_path),
        "-ss",
        f"{start:.3f}",
        "-to",
        f"{end:.3f}",
        "-c:v",
        codec,
        "-crf",
        str(crf),
        "-preset",
        preset,
        "-c:a",
        "copy",
        str(out_path),
    ]

    try:
        subprocess.run(cmd, check=True)  # nosec
        logger.info("🎬 Découpe %03d : %.2fs → %.2fs → %s", index, start, end, out_name)
        # logger.debug(f"Session cut ({session}):")
        # 🧠 Mise à jour du segment dans la session
        if session:
            logger.debug(f"session.segments : {session.segments}")
            seg = next((s for s in session.segments if s.id == index), None)
            logger.debug(f"seg : {seg}")
            if seg:
                seg.filename_predicted = out_name
                seg.output_path = str(out_path)
                seg.compute_duration()
                seg.ai_status = "done"
                seg.error = None
                session.last_updated = datetime.now().isoformat()
                logger.debug("✅ Segment %03d mis à jour dans la session.", index)

                # 💾 Sauvegarde immédiate
                if state_path:
                    session.save(str(state_path))
                    logger.debug("💾 Session sauvegardée après découpe du segment %03d.", index)

        return out_path

    except subprocess.CalledProcessError as err:
        logger.error("❌ Échec découpe %03d: %s", index, err)

        # ❗ Enregistrement de l’erreur dans le JSON
        if session:
            seg = next((s for s in session.segments if s.id == index), None)
            if seg:
                seg.error = str(err)
                seg.ai_status = "failed"
                session.errors.append(f"Erreur segment {index}: {err}")
                if state_path:
                    session.save(str(state_path))
        return None


def ensure_safe_video_format(video_path: str) -> str:
    ext = Path(video_path).suffix.lower()
    if ext not in SAFE_FORMATS:
        safe_path = Path(video_path).with_suffix(".mp4")
        ffmpeg.input(video_path).output(
            str(safe_path),
            vcodec=VCODEC,
            preset=PRESET,
            rc=RC,
            cq=CQ,
            pix_fmt=PIX_FMT,
        ).run(quiet=True, overwrite_output=True)
        return str(safe_path)
    return video_path
