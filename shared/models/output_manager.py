""" """

from __future__ import annotations

from pathlib import Path

from comfyui_router.output.output import wait_for_output_v2
from shared.models.config_manager import CONFIG
from shared.models.videojob import VideoJob
from shared.utils.logger import get_logger

logger = get_logger(__name__)

STABLE_TIME = CONFIG.comfyui_router["wait_for_output"]["stable_time"]
CHECK_INTERVAL = CONFIG.comfyui_router["wait_for_output"]["check_interval"]
TIMEOUT = CONFIG.comfyui_router["wait_for_output"]["timeout"]


class OutputManager:
    def __init__(self) -> None:
        self.logger = logger

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
