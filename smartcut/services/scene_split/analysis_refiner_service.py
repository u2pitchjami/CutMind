from __future__ import annotations

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.logger import LoggerProtocol, ensure_logger
from smartcut.models.scene_analysis import SceneAnalysis
from smartcut.services.scene_split.analysis_detector_service import (
    detect_scenes_from_analysis,
)


def refine_long_segments(
    analysis: SceneAnalysis,
    scenes: list[tuple[float, float]],
    thresholds: list[int],
    min_duration: float,
    max_duration: float,
    logger: LoggerProtocol | None = None,
) -> list[tuple[float, float]]:
    """
    Raffine récursivement les segments trop longs à partir
    d'une analyse vidéo déjà présente en mémoire.

    Aucun accès vidéo n'est effectué dans cette fonction.
    """
    logger = ensure_logger(logger, __name__)
    refined: list[tuple[float, float]] = []

    try:
        for start, end in scenes:
            duration = end - start

            if duration <= 0.0:
                logger.warning(
                    "Segment invalide ignoré : %.3f -> %.3f",
                    start,
                    end,
                )
                continue

            if duration < 0.8 * max_duration:
                refined.append((start, end))
                logger.debug(
                    "Segment conservé : %.3f -> %.3f (%.3f s)",
                    start,
                    end,
                    duration,
                )
                continue

            sub_scenes: list[tuple[float, float]] = []
            remaining_thresholds: list[int] = []

            for threshold_index, threshold in enumerate(thresholds):
                logger.debug(
                    "Raffinage RAM %.3f -> %.3f avec threshold=%d",
                    start,
                    end,
                    threshold,
                )

                sub_scenes = detect_scenes_from_analysis(
                    analysis,
                    threshold=threshold,
                    start=start,
                    end=end,
                    min_duration=min_duration,
                )

                if not sub_scenes:
                    continue

                remaining_thresholds = thresholds[threshold_index + 1 :]

                logger.debug(
                    "%d sous-segments détectés à threshold=%d",
                    len(sub_scenes),
                    threshold,
                )
                break

            if not sub_scenes:
                refined.append((start, end))
                logger.debug(
                    "Aucun raffinement possible : %.3f -> %.3f",
                    start,
                    end,
                )
                continue

            for sub_start, sub_end in sub_scenes:
                sub_duration = sub_end - sub_start

                if sub_duration > max_duration and remaining_thresholds:
                    logger.debug(
                        "Raffinage récursif : %.3f -> %.3f",
                        sub_start,
                        sub_end,
                    )

                    refined.extend(
                        refine_long_segments(
                            analysis=analysis,
                            scenes=[(sub_start, sub_end)],
                            thresholds=remaining_thresholds,
                            min_duration=min_duration,
                            max_duration=max_duration,
                            logger=logger,
                        )
                    )
                    continue

                # Diagnostic : le segment est toujours trop long,
                # mais tous les thresholds ont été épuisés.
                if sub_duration > max_duration and not remaining_thresholds:
                    start_frame = analysis.seconds_to_frame(sub_start)
                    end_frame = analysis.seconds_to_frame(sub_end)

                    scores = [score for score in analysis.content_values[start_frame:end_frame] if score is not None]

                    if scores:
                        logger.warning(
                            (
                                "Segment > max_duration après épuisement des thresholds : "
                                "%.3f -> %.3f | duration=%.3fs | "
                                "content_val max=%.3f"
                            ),
                            sub_start,
                            sub_end,
                            sub_duration,
                            max(scores),
                        )
                    else:
                        logger.warning(
                            ("Segment > max_duration sans score disponible : %.3f -> %.3f | duration=%.3fs"),
                            sub_start,
                            sub_end,
                            sub_duration,
                        )

                refined.append((sub_start, sub_end))

        return sorted(
            refined,
            key=lambda segment: segment[0],
        )

    except CutMindError as err:
        raise err.with_context(
            get_step_ctx(
                {
                    "duration": analysis.duration,
                    "fps": analysis.fps,
                }
            )
        ) from err

    except Exception as exc:
        raise CutMindError(
            "Erreur lors du raffinage des scènes en mémoire.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx(
                {
                    "duration": analysis.duration,
                    "fps": analysis.fps,
                }
            ),
        ) from exc
