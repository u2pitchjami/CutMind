""" """

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import psutil

from comfyui_router.comfyui.comfyui_workflow import optimal_batch_size
from comfyui_router.ffmpeg.ffmpeg_command import get_fps, get_resolution, get_total_frames, video_has_audio
from shared.models.config_manager import CONFIG
from shared.utils.logger import get_logger

logger = get_logger(__name__)


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

    def compute_optimal_batch(self, min_size: int, max_size: int) -> None:
        """
        Calcule le nombre de frames par batch selon les limites données.
        Appelé après que le workflow soit connu (donc après adaptation dynamique).
        """
        self.nb_frames_batch = optimal_batch_size(total_frames=self.nb_frames, min_size=min_size, max_size=max_size)

    def apply_adaptive_batch(self, wf_path: Path) -> None:
        """
        Calcule dynamiquement la taille de batch optimale
        en fonction du workflow et de la mémoire disponible.
        """

        try:
            adaptive_cfg = CONFIG.comfyui_router["adaptive_batch"]
            batch_policy = adaptive_cfg.get("batch_policy", {})
            profiles = adaptive_cfg.get("workflow_profiles", {})

            wf_name = wf_path.stem if wf_path else "unknown"
            profile = profiles.get(wf_name, {})

            per_frame_cost = profile.get("per_frame_cost_percent", 0.1)
            base_max = profile.get("base_max", 100)
            hard_ceiling = profile.get("hard_ceiling", base_max)

            mem = psutil.virtual_memory()
            ram_free_ratio = mem.available / mem.total

            caps = batch_policy.get("ram_caps", {})
            if ram_free_ratio >= caps["high_free"]["threshold"]:
                cap_target = caps["high_free"]["cap"]
            elif ram_free_ratio >= caps["mid_free"]["threshold"]:
                cap_target = caps["mid_free"]["cap"]
            else:
                cap_target = caps["low_free"]["cap"]

            baseline = 25.0
            spike_margin = batch_policy.get("init_spike_margin", 0.05)
            cap_eff = (cap_target - spike_margin) * 100

            batch_dynamic = int(
                max(
                    batch_policy["global"]["min_size"],
                    min(hard_ceiling, ((cap_eff - baseline) / per_frame_cost)),
                )
            )

            self.nb_frames_batch = batch_dynamic
            logger.info(
                "🧠 [AdaptiveBatch] %s | RAM libre: %.1f%% | cap: %.0f%% | batch: %d (ceil %d)",
                wf_name,
                ram_free_ratio * 100,
                cap_target * 100,
                batch_dynamic,
                hard_ceiling,
            )

        except Exception as e:
            logger.warning("[AdaptiveBatch] Erreur calcul batch dynamique: %s", e)
