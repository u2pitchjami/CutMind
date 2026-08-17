from __future__ import annotations

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.logger import LoggerProtocol, ensure_logger
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
    logger: LoggerProtocol | None = None,
) -> list[tuple[float, float]]:
    """
    Pipeline complet (scenedetect → refine → gaps → refine final).

    Version pure, sans logs.
    """
    logger = ensure_logger(logger, __name__)
    logger.debug("🔍 Début de la détection adaptative des scènes pour : %s", video_path)
    try:
        # Étape 1 : détection initiale
        scenes = detect_initial_scenes(
            video_path=video_path,
            threshold=initial_threshold,
            downscale_factor=downscale_factor,
            min_scene_len=min_duration,
            logger=logger,
        )

        # Préparation des seuils
        thresholds = list(range(initial_threshold - threshold_step, min_threshold - 1, -threshold_step))
        logger.debug("🔍 Seuils pour raffinage : %s", thresholds)
        # Étape 2 : raffinage
        refined = refine_long_segments(video_path, scenes, thresholds, min_duration, max_duration, logger=logger)
        logger.debug("🔍 Raffinage terminé, %d segments après raffinage.", len(refined))
        # Étape 3 : gaps
        refined = fill_missing_segments(refined, duration)
        logger.debug("🔍 Gaps ajoutés, %d segments après ajout des gaps.", len(refined))
        # Étape 4 : second raffinage pour les gaps longs
        refined = refine_long_segments(video_path, refined, thresholds, min_duration, max_duration, logger=logger)
        logger.debug("🔍 Second raffinage terminé, %d segments après raffinage.", len(refined))

        # Nettoyage des micro-segments
        refined = [seg for seg in refined if (seg[1] - seg[0]) >= min_duration]
        logger.debug("🔍 Nettoyage des micro-segments terminé, %d segments finaux.", len(refined))

        # Couverture
        covered = sum(e - s for s, e in refined)
        logger.debug(
            "🔍 Couverture totale des segments : %.2f / %.2f (%.2f%%)", covered, duration, (covered / duration) * 100
        )
        if covered < 0.8 * duration:
            raise CutMindError(
                "❌ Couverture insuffisante après segmentation adaptative",
                code=ErrCode.UNEXPECTED,
                ctx=get_step_ctx(
                    {
                        "video_path": video_path,
                        "covered": covered,
                        "duration": duration,
                    }
                ),
            )

        return refined
    except CutMindError as err:
        raise err.with_context(get_step_ctx({"video_path": video_path})) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur lors de la détection de scènes.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video_path": video_path}),
        ) from exc
