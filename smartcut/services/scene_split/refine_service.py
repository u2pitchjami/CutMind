from __future__ import annotations

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.logger import LoggerProtocol, ensure_logger
from smartcut.executors.pyscenedetect_executor import SceneDetectionSession
from smartcut.services.scene_split.detector_service import detect_initial_scenes


def refine_long_segments(
    session: SceneDetectionSession,
    scenes: list[tuple[float, float]],
    thresholds: list[int],
    min_duration: float,
    max_duration: float,
    logger: LoggerProtocol | None = None,
) -> list[tuple[float, float]]:
    """Raffine récursivement les segments trop longs."""

    logger = ensure_logger(logger, __name__)
    refined: list[tuple[float, float]] = []

    try:
        for start, end in scenes:
            duration = end - start

            if duration < 0.8 * max_duration:
                refined.append((start, end))
                continue

            sub_scenes: list[tuple[float, float]] = []
            remaining_thresholds: list[int] = []

            for threshold_index, threshold in enumerate(thresholds):
                logger.debug(
                    "🔍 Raffinage %.2f → %.2f, threshold=%d",
                    start,
                    end,
                    threshold,
                )

                sub_scenes = detect_initial_scenes(
                    session=session,
                    threshold=threshold,
                    start=start,
                    end=end,
                    min_scene_len=min_duration,
                    logger=logger,
                )

                if sub_scenes:
                    remaining_thresholds = thresholds[threshold_index + 1 :]
                    break

            if not sub_scenes:
                refined.append((start, end))
                logger.debug(
                    "🔍 Segment non raffiné : %.2f → %.2f",
                    start,
                    end,
                )
                continue

            for sub_start, sub_end in sub_scenes:
                sub_duration = sub_end - sub_start

                if sub_duration > max_duration and remaining_thresholds:
                    refined.extend(
                        refine_long_segments(
                            session=session,
                            scenes=[(sub_start, sub_end)],
                            thresholds=remaining_thresholds,
                            min_duration=min_duration,
                            max_duration=max_duration,
                            logger=logger,
                        )
                    )
                else:
                    refined.append((sub_start, sub_end))

        return sorted(
            refined,
            key=lambda segment: segment[0],
        )

    except CutMindError as err:
        raise err.with_context(get_step_ctx({"video_path": session.video_path})) from err

    except Exception as exc:
        raise CutMindError(
            "❌ Erreur lors du raffinage des scènes.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video_path": session.video_path}),
        ) from exc
