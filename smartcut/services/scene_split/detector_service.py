from __future__ import annotations

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.logger import LoggerProtocol, ensure_logger
from smartcut.executors.pyscenedetect_executor import run_pyscenedetect


def detect_initial_scenes(
    video_path: str,
    threshold: float,
    downscale_factor: int,
    start: float | None = None,
    end: float | None = None,
    min_scene_len: float = 15.0,
    logger: LoggerProtocol | None = None,
) -> list[tuple[float, float]]:
    """
    Détection PySceneDetect avec filtrage start/end.

    Version propre : aucune dépendance, aucun logger.
    """
    logger = ensure_logger(logger, __name__)
    logger.debug("🔍 Début de la détection initiale des scènes pour : %s", video_path)
    try:
        scenes = run_pyscenedetect(
            video_path=video_path,
            threshold=threshold,
            downscale=downscale_factor,
            start=start,
            end=end,
            min_scene_len=min_scene_len,
        )
        logger.debug("🔍 Détection initiale terminée, %d scènes détectées.", len(scenes))
        filtered: list[tuple[float, float]] = []

        for s, e in scenes:
            if start and e <= start:
                continue
            if end and s >= end:
                continue

            s2 = max(s, start or 0.0)
            e2 = min(e, end or e)

            filtered.append((s2, e2))

        return filtered
    except CutMindError as err:
        raise err.with_context(get_step_ctx({"video_path": video_path})) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur lors de la détection de scènes.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video_path": video_path}),
        ) from exc
