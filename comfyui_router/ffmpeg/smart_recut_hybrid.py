""" """

from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess

from shared.executors.ffmpeg_utils import get_duration
from shared.utils.config import TRASH_DIR
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger

RE_PTS_TIME = re.compile(r"pts_time[:=](\d+(?:\.\d+)?)")
RE_SCENE_SCORE = re.compile(r"(?:lavfi\.)?scene_score=(\d+(?:\.\d+)?)")


@with_child_logger
def detect_scene_changes_with_scores(
    video_path: Path, threshold: float = 0.005, logger: LoggerProtocol | None = None
) -> list[tuple[float, float]]:
    """
    Détecte les changements de scène et renvoie (timestamp, score).
    """
    logger = ensure_logger(logger, __name__)
    cmd: list[str] = [
        "ffmpeg",
        "-hide_banner",
        "-i",
        str(video_path),
        "-filter:v",
        f"select=gt(scene\\,{threshold}),metadata=print",
        "-f",
        "null",
        "-",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as err:
        logger.error("Erreur FFmpeg: %s", err)
        return []

    times = [float(m.group(1)) for m in RE_PTS_TIME.finditer(result.stderr)]
    scores = [float(m.group(1)) for m in RE_SCENE_SCORE.finditer(result.stderr)]
    return list(zip(times, scores, strict=False))


def compute_dynamic_margin(score: float) -> float:
    """
    Retourne un margin selon la brutalité du changement.
    """
    if score < 0.05:
        return 0.5
    if score < 0.2:
        return 0.3
    return 0.1


@with_child_logger
def auto_threshold_pass(
    video_path: Path, base_threshold: float = 0.005, logger: LoggerProtocol | None = None
) -> list[tuple[float, float]]:
    """
    Fait une détection, puis relance avec un seuil réduit seulement si rien trouvé.
    """
    logger = ensure_logger(logger, __name__)
    cuts = detect_scene_changes_with_scores(video_path, base_threshold, logger=logger)
    if not cuts:
        new_threshold = base_threshold / 2
        logger.info("⚠️ Aucune scène détectée → nouvelle passe avec threshold = %.4f", new_threshold)
        cuts = detect_scene_changes_with_scores(video_path, new_threshold, logger=logger)
    return cuts


def choose_best_cuts(
    cuts: list[tuple[float, float]], duration: float
) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
    """
    Renvoie (cut_debut, cut_fin) basés sur les scores et positions.
    """
    if not cuts:
        return None, None

    valid_cuts = [(t, s) for (t, s) in cuts if 0.5 < t < duration]
    if not valid_cuts:
        return None, None

    # Premier cut fort (début)
    first_cut = next(((t, s) for (t, s) in valid_cuts if s > 0.02), None)

    # Dernier cut fort (fin)
    # Dernier cut fort proche de la fin (évite les coupures à mi-parcours)
    last_cut = next(
        (
            (t, s)
            for (t, s) in reversed(valid_cuts)
            if s > 0.02 and t > duration * 0.8  # au moins dans les 20% de fin
        ),
        None,
    )

    return first_cut, last_cut


@with_child_logger
def smart_recut_hybrid(
    video_path: Path,
    threshold: float = 0.005,
    use_cuda: bool = True,
    cleanup: bool = True,
    logger: LoggerProtocol | None = None,
) -> Path:
    """
    Découpe la vidéo au début et à la fin selon les changements de scène.
    """
    logger = ensure_logger(logger, __name__)
    duration = get_duration(video_path)
    if duration == 0:
        logger.error("Impossible de déterminer la durée de %s", video_path)
        return video_path

    cuts = auto_threshold_pass(video_path, threshold, logger=logger)
    logger.info("Cuts détectés: %s", [(round(t, 3), round(s, 3)) for (t, s) in cuts])

    cut_start, cut_end = choose_best_cuts(cuts, duration)

    if not cut_start and not cut_end:
        logger.info("⚙️ Aucun changement significatif → pas de recut.")
        return video_path

    start_time = round((cut_start[0] + compute_dynamic_margin(cut_start[1])) if cut_start else 0.0, 3)
    logger.info("DEBUG: cut_end = %s", cut_end)

    end_time = round((cut_end[0] - compute_dynamic_margin(cut_end[1])) if cut_end else duration, 3)

    if end_time <= start_time:
        logger.warning("Durée recoupée incohérente → pas de recut.")
        return video_path

    output_path = video_path.with_name(video_path.stem + "_smart_trimmed.mp4")
    codec = "hevc_nvenc" if use_cuda else "libx265"
    hwaccel = "cuda" if use_cuda else "auto"
    logger.info(
        "Découpage : début %.3fs / fin %.3fs (durée originale %.3fs) → %s",
        start_time,
        end_time,
        duration,
        output_path.name,
    )

    cmd: list[str] = [
        "ffmpeg",
        "-y",
        "-hwaccel",
        hwaccel,
        "-i",
        str(video_path),
        "-ss",
        str(round(start_time, 3)),
        "-to",
        str(round(end_time, 3)),
        "-c:v",
        codec,
        "-preset",
        "slow" if not use_cuda else "p7",  # "p7" = preset nvenc haute qualité
        "-crf",
        "17",
        "-c:a",
        "copy",
        str(output_path),
    ]

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as err:
        logger.error("Erreur FFmpeg: %s", err)
        return video_path

    if cleanup:
        try:
            shutil.move(video_path, TRASH_DIR / video_path.name)
            logger.debug(f"🧹 Fichier original déplacé vers TRASH_DIR : {video_path.name}")
        except Exception as e:
            logger.warning(f"⚠️ Impossible de déplacer {video_path.name} : {e}")

    logger.info("✅ Recut terminé : %s", output_path)
    return output_path


if __name__ == "__main__":
    path = Path("/mnt/user/Zin-progress/comfyui-nvidia/basedir/output/OK/test3.mp4")
    smart_recut_hybrid(video_path=path, use_cuda=False)
