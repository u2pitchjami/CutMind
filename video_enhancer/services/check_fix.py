""" """

from __future__ import annotations

from shared.executors.ffprobe_utils import (
    get_fps,
)
from shared.models.db_models import Segment
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.models.videoprep import VideoPrepared
from shared.services.ensure_resolution import ensure_resolution
from shared.services.smart_recut_hybrid import smart_recut_hybrid
from shared.services.video_preparation import prepare_video
from shared.utils.datas import resolution_str_to_tuple
from shared.utils.logger import LoggerProtocol, ensure_logger
from shared.utils.settings import get_settings
from video_enhancer.ffmpeg.ffmpeg_command import convert_to_60fps
from video_enhancer.models_cr.videojob import VideoJob


def check_fix_workflow(
    job: VideoJob,
    segment: Segment,
    cuda: bool,
    logger: LoggerProtocol | None = None,
) -> tuple[VideoJob, Segment, VideoPrepared]:
    """
    Workflow de check & fix pour un segment donné.
    """
    logger = ensure_logger(logger, __name__)
    settings = get_settings()
    CLEANUP = settings.router_processor.cleanup
    DELTA_DURATION = settings.router_processor.delta_duration
    RATIO_DURATION = settings.router_processor.ratio_duration
    TARGET_FPS = settings.router_processor.target_fps

    try:
        # 🧩 Étape 3 : Check
        meta = prepare_video(job.path, logger=logger)
        job.fps_out = meta.fps
        job.resolution_out = resolution_str_to_tuple(meta.resolution)

        # 🧩 Étape 4 : Fix Resolution
        res_out = job.resolution_out
        job.path, job.resolution_out = ensure_resolution(job.path, job.resolution_out, logger=logger)
        if job.resolution_out != res_out:
            segment.add_tag("resolution_fixed")

        # 🧩 Étape 5 : Fix FPS
        if job.fps_out > TARGET_FPS:
            temp_output = job.path.with_name(f"{job.path.stem}_{TARGET_FPS}fps.mp4")
            logger.debug(f"fps_out > {TARGET_FPS} -> temp_output : {temp_output}")
            job.path = convert_to_60fps(job.path, temp_output, TARGET_FPS)
            logger.info(f"✅ Conversion {TARGET_FPS} FPS terminée : {job.path.stem}")
            job.fps_out = get_fps(job.path)

        # 🧩 Étape 6 : Smart Recut
        logger.info(f"🔧 Fichier à recouper intelligemment : {job.path}")
        logger.info(
            "smart_recut_hybrid input | exists=%s size=%d path=%s",
            job.path.exists(),
            job.path.stat().st_size if job.path.exists() else -1,
            job.path,
        )
        job.path = smart_recut_hybrid(job.path, use_cuda=cuda, cleanup=CLEANUP, logger=logger)
        logger.info(f"✅ Smart recut terminé : {job.path}")

        if meta.duration and segment.duration:
            expected = round(segment.duration, 3)
            delta = abs(meta.duration - expected)
            ratio = delta / expected if expected else 0

            if delta > DELTA_DURATION or ratio > RATIO_DURATION:
                logger.warning(
                    "⏱️ ⚠️ Écart de durée segment %s : attendu=%.2fs / réel=%.2fs (∆ %.2fs, %.1f%%)",
                    segment.id,
                    expected,
                    meta.duration,
                    delta,
                    ratio * 100,
                )
                if segment.tags == "" or "duration_warning" not in segment.tags:
                    logger.debug(f"segment.tags = {segment.tags}")
                    segment.add_tag("duration_warning")
                    logger.debug(f"Tag ajouté : segment.tags = {segment.tags}")
        elif not meta.duration:
            logger.warning(
                "⏱️ Impossible de lire la durée de sortie pour %s",
                job.path.name,
            )

        return job, segment, meta

    except CutMindError:
        raise
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur check & fix.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx(
                {
                    "job.path.name": job.path.name,
                    "segment": segment.filename_predicted,
                }
            ),
        ) from exc
