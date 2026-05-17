""" """

from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path

TARGET_HEIGHT = 1080
TARGET_FPS = 60
MAX_UPSCALE_FACTOR = 4
VALID_FPS_FACTORS = (2, 4, 8)


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
    upscale_factor: int | None = field(init=False, default=None)
    rife_passes: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        """Compute processing decisions."""

        self.upscale_factor = self._compute_upscale_factor()
        self.rife_passes = self._compute_rife_passes()

    def _compute_upscale_factor(self) -> int | None:
        """Compute Real-ESRGAN scale factor."""
        _, height = self.resolution

        if height >= TARGET_HEIGHT:
            return None

        factor = math.ceil(TARGET_HEIGHT / height)

        return min(factor, MAX_UPSCALE_FACTOR)

    def _compute_rife_passes(self) -> int:
        """Compute required RIFE passes."""

        if self.fps_in >= TARGET_FPS:
            return 0

        current_fps = self.fps_in
        passes = 0

        while current_fps < TARGET_FPS:
            current_fps *= 2
            passes += 1

        return passes
