""" """

from __future__ import annotations

from pathlib import Path
import shutil

from comfyui_router.executors.smart_recut_hybrid_exec import (
    auto_threshold_pass,
    choose_best_cuts,
    compute_dynamic_margin,
)
from shared.executors.ffmpeg_utils import get_duration
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.config import TRASH_DIR
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from smartcut.executors.ffmpeg_cut_executor import FfmpegCutExecutor


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
    logger.debug("Début de la découpe de %s", video_path)
    logger.info(
        "smart_recut_hybrid input | exists=%s size=%d path=%s",
        video_path.exists(),
        video_path.stat().st_size if video_path.exists() else -1,
        video_path,
    )
    executor = FfmpegCutExecutor()

    try:
        duration = get_duration(video_path)
        logger.debug("durée de %s: %s", video_path, duration)
        if duration == 0:
            logger.error("Impossible de déterminer la durée de %s", video_path)
            return video_path

        cuts = auto_threshold_pass(video_path, threshold)
        # logger.info("Cuts détectés: %s", [(round(t, 3), round(s, 3)) for (t, s) in cuts])

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

        output_path = video_path.with_name(f"{video_path.stem}_smart_trimmed.mp4")
        executor.cut(str(video_path), start_time, end_time, str(output_path), logger=logger)

        logger.info(
            "Découpage : début %.3fs / fin %.3fs (durée originale %.3fs) → %s",
            start_time,
            end_time,
            duration,
            output_path.name,
        )

        if cleanup:
            try:
                shutil.move(video_path, TRASH_DIR / video_path.name)
                logger.debug(f"🧹 Fichier original déplacé vers TRASH_DIR : {video_path.name}")
            except Exception as e:
                logger.warning(f"⚠️ Impossible de déplacer {video_path.name} : {e}")

        logger.info("✅ Recut terminé : %s", output_path)
        return output_path
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur innatendue lors de smart_cut_hybrid.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video_path": video_path}),
            original_exception=exc,
        ) from exc
