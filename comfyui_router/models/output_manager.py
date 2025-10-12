from pathlib import Path

from comfyui_router.models.videojob import VideoJob
from comfyui_router.output.output import wait_for_output_v2
from comfyui_router.utils.logger import get_logger

logger = get_logger("Comfyui Router")


class OutputManager:
    def __init__(self) -> None:
        self.logger = logger

    def wait_for_output(self, video_job: VideoJob) -> Path | None:
        """Récupère le fichier final généré par ComfyUI."""
        file = wait_for_output_v2(video_job.path.stem, expect_audio=video_job.has_audio)
        if file:
            video_job.output_file = file
            return Path(file)
        return None
