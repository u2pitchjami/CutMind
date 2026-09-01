from __future__ import annotations

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.logger import LoggerProtocol, ensure_logger
from smartcut.executors.pyscenedetect_executor import SceneDetectionSession


def detect_initial_scenes(
    session: SceneDetectionSession,
    threshold: float,
    start: float | None = None,
    end: float | None = None,
    min_scene_len: float = 15.0,
    logger: LoggerProtocol | None = None,
) -> list[tuple[float, float]]:
    """Détection de scènes utilisant une session PySceneDetect existante."""

    logger = ensure_logger(logger, __name__)

    try:
        logger.debug(
            "🔍 Détection scènes threshold=%.2f start=%s end=%s",
            threshold,
            start,
            end,
        )

        scenes = session.detect(
            threshold=threshold,
            start=start,
            end=end,
            min_scene_len=min_scene_len,
        )

        filtered: list[tuple[float, float]] = []

        for scene_start, scene_end in scenes:
            if start is not None and scene_end <= start:
                continue

            if end is not None and scene_start >= end:
                continue

            clipped_start = max(
                scene_start,
                start if start is not None else 0.0,
            )

            clipped_end = min(
                scene_end,
                end if end is not None else scene_end,
            )

            filtered.append((clipped_start, clipped_end))

        logger.debug(
            "🔍 %d scènes détectées.",
            len(filtered),
        )

        return filtered

    except CutMindError as err:
        raise err.with_context(get_step_ctx({"video_path": session.video_path})) from err

    except Exception as exc:
        raise CutMindError(
            "❌ Erreur lors de la détection de scènes.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video_path": session.video_path}),
        ) from exc
