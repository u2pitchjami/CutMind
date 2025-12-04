""" """

from __future__ import annotations

from pathlib import Path

from comfyui_router.models_cr.videojob import VideoJob
from comfyui_router.services.wait_for_output import wait_for_output_v2
from shared.utils.settings import get_settings

settings = get_settings()

STABLE_TIME = settings.router_wait_output.stable_time
CHECK_INTERVAL = settings.router_wait_output.check_interval
TIMEOUT = settings.router_wait_output.timeout


class OutputManager:
    def wait_for_output(self, video_job: VideoJob) -> Path | None:
        """
        Récupère le fichier final généré par ComfyUI.
        """
        file = wait_for_output_v2(
            filename_prefix=video_job.path.stem,
            expect_audio=video_job.has_audio,
            stable_time=STABLE_TIME,
            check_interval=CHECK_INTERVAL,
            timeout=TIMEOUT,
        )
        if file:
            video_job.output_file = file
            return Path(file)
        return None
