from dataclasses import dataclass
from pathlib import Path

from comfyui_router.ffmpeg.ffmpeg_command import get_fps, get_resolution, video_has_audio
from comfyui_router.utils.logger import get_logger

logger = get_logger("Comfyui Router")


@dataclass
class VideoJob:
    path: Path
    resolution: tuple[int, int] = (0, 0)
    fps_in: float = 0.0
    fps_out: float = 0.0
    has_audio: bool = False
    workflow_path: Path | None = None
    output_file: Path | None = None

    def analyze(self) -> None:
        """Récupère les métadonnées vidéo via ffprobe."""
        self.resolution = get_resolution(self.path)
        self.fps_in = get_fps(self.path)
        self.has_audio = video_has_audio(self.path)
