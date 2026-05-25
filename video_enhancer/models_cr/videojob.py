""" """

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from shared.utils.settings import get_settings


@dataclass
class VideoJob:
    path: Path
    work_key: str
    resolution: tuple[int, int] = (0, 0)
    resolution_out: tuple[int, int] = (0, 0)
    fps_in: float = 0.0
    fps_out: float = 0.0
    nb_frames: int = 0
    codec_in: str | None = None
    bitrate_in: int | None = None
    duration_in: float = 0.0
    filesize_mb_in: float = 0.0
    has_audio: bool = False
    output_file: Path | None = None
    upscale_factor: str | None = field(init=False, default=None)
    rife_passes: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        """Compute processing decisions."""

        self.upscale_factor = self._compute_upscale_factor()
        self.rife_passes = self._compute_rife_passes()

    def _compute_upscale_factor(self) -> str | None:
        """Compute Real-ESRGAN scale factor.

        Real-ESRGAN x4plus est stable avec x2 ou x4 uniquement.
        Le resize final est géré plus tard via FFmpeg.
        """
        settings = get_settings()
        TARGET_HEIGHT = settings.router_processor.target_height
        UPSCALE_RATIO = settings.router_processor.upscale_ratio
        UPSCALE_RATIO_UP = settings.router_processor.upscale_ratio_up
        UPSCALE_RATIO_DOWN = settings.router_processor.upscale_ratio_down

        _, height = self.resolution

        if height >= TARGET_HEIGHT:
            return None

        ratio = TARGET_HEIGHT / height

        if ratio <= UPSCALE_RATIO:
            return UPSCALE_RATIO_DOWN

        return UPSCALE_RATIO_UP

    def _compute_rife_passes(self) -> int:
        """Compute required RIFE passes."""
        settings = get_settings()
        TARGET_FPS = settings.router_processor.target_fps

        if self.fps_in >= TARGET_FPS:
            return 0

        current_fps = self.fps_in
        passes = 0

        while current_fps < TARGET_FPS:
            current_fps *= 2
            passes += 1

        return passes
