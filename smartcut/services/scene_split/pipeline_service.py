from __future__ import annotations

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.logger import LoggerProtocol, ensure_logger
from smartcut.executors.pyscenedetect_executor import SceneDetectionSession
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
    """Détection adaptative des scènes."""

    logger = ensure_logger(logger, __name__)

    try:
        session = SceneDetectionSession(
            video_path,
            downscale=downscale_factor,
        )

        scenes = detect_initial_scenes(
            session=session,
            threshold=initial_threshold,
            min_scene_len=min_duration,
            logger=logger,
        )

        thresholds = list(
            range(
                initial_threshold - threshold_step,
                min_threshold - 1,
                -threshold_step,
            )
        )

        refined = refine_long_segments(
            session=session,
            scenes=scenes,
            thresholds=thresholds,
            min_duration=min_duration,
            max_duration=max_duration,
            logger=logger,
        )

        refined = fill_missing_segments(
            refined,
            duration,
        )

        refined = refine_long_segments(
            session=session,
            scenes=refined,
            thresholds=thresholds,
            min_duration=min_duration,
            max_duration=max_duration,
            logger=logger,
        )

        refined = [segment for segment in refined if segment[1] - segment[0] >= min_duration]

        covered = sum(end - start for start, end in refined)

        coverage = covered / duration if duration > 0.0 else 0.0

        logger.debug(
            "🔍 Couverture : %.2f / %.2f (%.2f%%)",
            covered,
            duration,
            coverage * 100.0,
        )

        if coverage < 0.8:
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
