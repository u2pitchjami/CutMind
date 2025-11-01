""" """

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from comfyui_router.comfyui.comfyui_workflow import optimal_batch_size
from comfyui_router.ffmpeg.ffmpeg_command import get_fps, get_resolution, get_total_frames, video_has_audio
from shared.models.config_manager import CONFIG
from shared.utils.logger import get_logger

logger = get_logger(__name__)


MIN_SIZE = CONFIG.comfyui_router["optimal_batch_size"]["min_size"]
MAX_SIZE = CONFIG.comfyui_router["optimal_batch_size"]["max_size"]


@dataclass
class VideoJob:
    path: Path
    resolution: tuple[int, int] = (0, 0)
    fps_in: float = 0.0
    fps_out: float = 0.0
    nb_frames: int = 0
    nb_frames_batch: int = 70
    has_audio: bool = False
    workflow_path: Path | None = None
    output_file: Path | None = None

    def analyze(self) -> None:
        """
        Récupère les métadonnées vidéo via ffprobe.
        """
        self.resolution = get_resolution(self.path)
        self.fps_in = get_fps(self.path)
        self.has_audio = video_has_audio(self.path)
        self.nb_frames = get_total_frames(self.path)
        self.nb_frames_batch = optimal_batch_size(total_frames=self.nb_frames, min_size=MIN_SIZE, max_size=MAX_SIZE)
