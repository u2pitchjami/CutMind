""" """

from __future__ import annotations

from typing import Any

from comfyui_router.comfyui.comfyui_command import run_comfy
from comfyui_router.comfyui.comfyui_workflow import (
    inject_video_path,
    load_workflow,
    route_workflow,
)
from comfyui_router.models_cr.videojob import VideoJob
from shared.models.config_manager import CONFIG
from shared.utils.logger import get_logger

logger = get_logger(__name__)

MIN_SIZE = CONFIG.comfyui_router["optimal_batch_size"]["min_size"]


class ComfyWorkflowManager:
    def __init__(self) -> None:
        self.logger = logger

    def prepare_workflow(self, video_job: VideoJob) -> dict[str, Any] | None:
        """
        Définit et charge le workflow adapté.
        """
        wf_path = route_workflow(video_job.path)
        if not wf_path:
            self.logger.info(f"❌ Ignorée (résolution trop basse) : {video_job.path.name}")
            return None

        # 🧠 Calcul du batch adaptatif
        video_job.apply_adaptive_batch(wf_path)
        video_job.workflow_path = wf_path
        # 🔢 Calcul concret des lots à partir du batch max déterminé
        video_job.compute_optimal_batch(min_size=MIN_SIZE, max_size=video_job.nb_frames_batch)

        # 🚀 Injection du workflow
        workflow = inject_video_path(load_workflow(wf_path), video_job.path, video_job.nb_frames_batch)
        return workflow

    def run(self, workflow: dict[str, Any]) -> bool:
        """
        Envoie le workflow à ComfyUI.
        """
        return run_comfy(workflow)
