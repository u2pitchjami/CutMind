from __future__ import annotations

from shared.models.exceptions import CutMindError, ErrCode
from smartcut.services.scene_split.detector_service import detect_initial_scenes
from smartcut.services.scene_split.gap_service import fill_missing_segments
from smartcut.services.scene_split.refine_service import refine_long_segments


def adaptive_scene_split(
    video_path: str,
    *,
    duration: float,
    initial_threshold: int,
    min_threshold: int,
    threshold_step: int,
    min_duration: float,
    max_duration: float,
    downscale_factor: int,
) -> list[tuple[float, float]]:
    """
    Pipeline complet (scenedetect → refine → gaps → refine final).
    Version pure, sans logs.
    """
    # Étape 1 : détection initiale
    scenes = detect_initial_scenes(
        video_path=video_path,
        threshold=initial_threshold,
        downscale_factor=downscale_factor,
        min_scene_len=min_duration,
    )

    # Préparation des seuils
    thresholds = list(range(initial_threshold - threshold_step, min_threshold - 1, -threshold_step))

    # Étape 2 : raffinage
    refined = refine_long_segments(
        video_path,
        scenes,
        thresholds,
        min_duration,
        max_duration,
    )

    # Étape 3 : gaps
    refined = fill_missing_segments(refined, duration)

    # Étape 4 : second raffinage pour les gaps longs
    refined = refine_long_segments(
        video_path,
        refined,
        thresholds,
        min_duration,
        max_duration,
    )

    # Nettoyage des micro-segments
    refined = [seg for seg in refined if (seg[1] - seg[0]) >= min_duration]

    # Couverture
    covered = sum(e - s for s, e in refined)
    if covered < 0.8 * duration:
        raise CutMindError(
            "Couverture insuffisante après segmentation adaptative",
            code=ErrCode.UNEXPECTED,
            ctx={
                "video_path": video_path,
                "covered": covered,
                "duration": duration,
            },
        )

    return refined
