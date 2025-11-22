""" """

from __future__ import annotations

from pathlib import Path

from scenedetect import open_video  # type: ignore

from shared.utils.config import ERROR_DIR_SC
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from smartcut.models_sc.smartcut_model import SmartCutSession
from smartcut.scene_split.pyscenedetect import (
    detect_scenes_with_pyscenedetect,
    fill_missing_segments,
    refine_long_segments,
)
from smartcut.scene_split.refine_with_tracking import refine_with_tracking
from smartcut.scene_split.split_utils import get_downscale_factor, move_to_error


@with_child_logger
def adaptive_scene_split(
    video_path: str,
    session: SmartCutSession,
    initial_threshold: int = 80,
    min_threshold: int = 5,
    threshold_step: int = 2,
    min_duration: float = 15.0,
    max_duration: float = 180.0,
    logger: LoggerProtocol | None = None,
) -> list[tuple[float, float]]:
    """
    Segmentation adaptative complète avec comblement de zones manquantes.
    """
    logger = ensure_logger(logger, __name__)
    logger.info(f"🚀 Début découpage adaptatif: {video_path}")

    # Récupération durée vidéo
    video = open_video(video_path)
    downscale = get_downscale_factor(video_path)
    logger.debug(f"📉 Downscale factor appliqué: {downscale}x")
    video_duration = video.duration.get_seconds()

    # Étape 1 : détection globale
    scenes = detect_scenes_with_pyscenedetect(
        video_path, threshold=initial_threshold, downscale_factor=downscale, logger=logger
    )
    logger.info(f"🎬 {len(scenes)} scènes initiales détectées à th={initial_threshold}")

    # Étape 2 : premier raffinage adaptatif
    thresholds: list[float] = list(range(initial_threshold - threshold_step, min_threshold - 1, -threshold_step))
    # refined = refine_long_segments(video_path, scenes, thresholds, min_duration, max_duration, logger=logger)
    refined = refine_with_tracking(session, scenes, thresholds, min_duration, max_duration, logger=logger)

    # Étape 2.5 : comblement des gaps APRÈS le raffinage
    refined = fill_missing_segments(refined, video_duration, logger=logger)
    logger.debug(f"📊 Total après comblement final des gaps: {len(refined)} segments (avec trous ajoutés)")

    # Étape 2.6 : re-raffinage dédié pour les gaps comblés
    logger.debug("🔁 Deuxième passe de raffinage dédiée aux segments comblés trop longs...")
    second_refined = []

    for s, e in refined:
        duration = e - s
        if duration > max_duration:
            logger.debug(f"🪚 Raffinage spécifique des gaps {s:.1f}s–{e:.1f}s (durée {duration:.1f}s)")
            # On descend plus bas en seuils que la première passe
            deep_thresholds: list[float] = list(range(initial_threshold, min_threshold - 1, -threshold_step))
            sub_scenes = refine_long_segments(
                video_path, [(s, e)], deep_thresholds, min_duration, max_duration, logger=logger
            )
            second_refined.extend(sub_scenes)
        else:
            second_refined.append((s, e))

    refined = sorted(second_refined, key=lambda x: x[0])

    # Deuxième passage de raffinage uniquement sur les gaps ajoutés
    refined = refine_long_segments(video_path, refined, thresholds, min_duration, max_duration, logger=logger)

    # Étape 3 : nettoyage (suppression micro-segments)
    refined = [seg for seg in refined if (seg[1] - seg[0]) >= min_duration]

    logger.info(f"✅ Découpage final: {len(refined)} scènes (raffinement + gaps inclus)")

    # Étape 4 : export CSV pour inspection ou LosslessCut
    # export_segments_csv(video_path, refined)

    # Vérification couverture
    covered = sum(e - s for s, e in refined)
    ratio = covered / video_duration
    if ratio > 0.999:
        logger.info(f"✅ Couverture complète ({covered:.1f}/{video_duration:.1f}s, {ratio * 100:.1f}%)")
    else:
        logger.warning(f"⚠️ Couverture partielle ({covered:.1f}/{video_duration:.1f}s, {ratio * 100:.1f}%)")
        last_end = 0.0
        for s, e in refined:
            if s - last_end > 1.0:
                logger.warning(f"   ↳ Trou détecté entre {last_end:.1f}s et {s:.1f}s")
            last_end = e
        if ratio < 0.8:
            move_to_error(file_path=Path(video_path), error_root=ERROR_DIR_SC, logger=logger)
            raise

    return refined
