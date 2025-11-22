""" """

from __future__ import annotations

from typing import Any

from comfyui_router.comfyui.comfyui_command import comfyui_path, run_comfy
from comfyui_router.comfyui.comfyui_workflow import (
    inject_video_path,
    load_workflow,
    route_workflow,
)
from comfyui_router.models_cr.videojob import VideoJob
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from shared.utils.settings import get_settings

settings = get_settings()
MIN_SIZE = settings.router_optimal_batch_size.min_size


class ComfyWorkflowManager:
    @with_child_logger
    def prepare_workflow(self, video_job: VideoJob, logger: LoggerProtocol | None = None) -> dict[str, Any] | None:
        """
        Définit et charge le workflow adapté.
        """
        logger = ensure_logger(logger, __name__)
        wf_path = route_workflow(video_job.path)
        if not wf_path:
            logger.info(f"❌ Ignorée (résolution trop basse) : {video_job.path.name}")
            return None

        # 🧠 Calcul du batch adaptatif
        video_job.apply_adaptive_batch(wf_path, logger=logger)
        video_job.workflow_path = wf_path
        video_job.workflow_name = wf_path.stem
        # 🔢 Calcul concret des lots à partir du batch max déterminé
        video_job.compute_optimal_batch(min_size=MIN_SIZE, max_size=video_job.nb_frames_batch)

        # 🚀 Injection du workflow
        if not video_job.comfyui_path:
            video_job.comfyui_path = comfyui_path(full_path=video_job.path)
        workflow = inject_video_path(
            load_workflow(wf_path), video_job.comfyui_path, video_job.nb_frames_batch, logger=logger
        )
        return workflow

    @with_child_logger
    def run(self, workflow: dict[str, Any], logger: LoggerProtocol | None = None) -> bool:
        """
        Envoie le workflow à ComfyUI.
        """
        logger = ensure_logger(logger, __name__)
        return run_comfy(workflow, logger=logger)
