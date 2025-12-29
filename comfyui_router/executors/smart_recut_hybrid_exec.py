""" """

from __future__ import annotations

from pathlib import Path
import re
import subprocess

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx

RE_PTS_TIME = re.compile(r"pts_time[:=](\d+(?:\.\d+)?)")
RE_SCENE_SCORE = re.compile(r"(?:lavfi\.)?scene_score=(\d+(?:\.\d+)?)")


def detect_scene_changes_with_scores(video_path: Path, threshold: float = 0.005) -> list[tuple[float, float]]:
    """
    Détecte les changements de scène et renvoie (timestamp, score).
    """
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
        times = [float(m.group(1)) for m in RE_PTS_TIME.finditer(result.stderr)]
        scores = [float(m.group(1)) for m in RE_SCENE_SCORE.finditer(result.stderr)]
        return list(zip(times, scores, strict=False))
    except subprocess.CalledProcessError as err:
        raise CutMindError(
            "❌ Erreur FFMPEG lors de la détection de changements de scènes.",
            code=ErrCode.FFMPEG,
            ctx=get_step_ctx({"video_path": video_path}),
        ) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur innatendue lors de la détection de changements de scènes.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video_path": video_path}),
        ) from exc


def compute_dynamic_margin(score: float) -> float:
    """
    Retourne un margin selon la brutalité du changement.
    """
    if score < 0.05:
        return 0.5
    if score < 0.2:
        return 0.3
    return 0.1


def auto_threshold_pass(video_path: Path, base_threshold: float = 0.005) -> list[tuple[float, float]]:
    """
    Fait une détection, puis relance avec un seuil réduit seulement si rien trouvé.
    """
    try:
        cuts = detect_scene_changes_with_scores(video_path, base_threshold)
        if not cuts:
            new_threshold = base_threshold / 2
            cuts = detect_scene_changes_with_scores(video_path, new_threshold)
        return cuts
    except CutMindError as err:
        raise err.with_context(get_step_ctx({"video_path": video_path})) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inatendue durant auto_threshold_pass.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video_path": video_path}),
        ) from exc


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
