""" """

from __future__ import annotations

from typing import Any

from comfyui_router.executors.comfyui.comfyui_command import comfyui_path, run_comfy
from comfyui_router.executors.comfyui.comfyui_workflow import (
    inject_video_path,
    load_workflow,
    route_workflow,
)
from comfyui_router.models_cr.videojob import VideoJob
from shared.utils.settings import get_settings

settings = get_settings()
MIN_SIZE = settings.router_optimal_batch_size.min_size


class ComfyWorkflowManager:
    def prepare_workflow(self, video_job: VideoJob) -> dict[str, Any] | None:
        """
        Définit et charge le workflow adapté.
        """
        wf_path = route_workflow(video_job.path)
        if not wf_path:
            return None

        # 🧠 Calcul du batch adaptatif
        video_job.apply_adaptive_batch(wf_path)
        video_job.workflow_path = wf_path
        video_job.workflow_name = wf_path.stem
        # 🔢 Calcul concret des lots à partir du batch max déterminé
        video_job.compute_optimal_batch(min_size=MIN_SIZE, max_size=video_job.nb_frames_batch)

        # 🚀 Injection du workflow
        if not video_job.comfyui_path:
            video_job.comfyui_path = comfyui_path(full_path=video_job.path)
        workflow = inject_video_path(load_workflow(wf_path), video_job.comfyui_path, video_job.nb_frames_batch)
        return workflow

    def run(self, workflow: dict[str, Any]) -> bool:
        """
        Envoie le workflow à ComfyUI.
        """
        run_comfy(workflow)
        return True
