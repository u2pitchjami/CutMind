from __future__ import annotations

from scenedetect import (  # type: ignore
    ContentDetector,
    FrameTimecode,
    SceneManager,
    StatsManager,
    open_video,
)

from shared.models.exceptions import CutMindError, ErrCode


class SceneDetectionSession:
    """Session PySceneDetect réutilisable pour une même vidéo."""

    def __init__(
        self,
        video_path: str,
        *,
        downscale: int = 1,
    ) -> None:
        if downscale < 1:
            raise ValueError("downscale doit être >= 1")

        self.video_path = video_path
        self.downscale = downscale

        try:
            self.video = open_video(video_path)
            self.stats_manager = StatsManager()
        except Exception as exc:
            raise CutMindError(
                "Impossible d'ouvrir la vidéo avec PySceneDetect",
                code=ErrCode.FFMPEG,
                ctx={
                    "video_path": video_path,
                    "internal_error": str(exc),
                    "type": type(exc).__name__,
                },
            ) from exc

    @property
    def frame_rate(self) -> float:
        """Retourne le framerate utilisé par PySceneDetect."""
        return float(self.video.frame_rate)

    def detect(
        self,
        *,
        threshold: float,
        min_scene_len: float,
        start: float | None = None,
        end: float | None = None,
    ) -> list[tuple[float, float]]:
        """Détecte les scènes sur une plage en réutilisant les stats."""

        try:
            min_scene_frames = max(
                1,
                round(min_scene_len * self.frame_rate),
            )

            scene_manager = SceneManager(
                stats_manager=self.stats_manager,
            )

            # Important : utiliser la même résolution pour toutes les passes,
            # sinon les content_val mis en cache ne correspondent plus.
            scene_manager.auto_downscale = False
            scene_manager.downscale = self.downscale

            scene_manager.add_detector(
                ContentDetector(
                    threshold=threshold,
                    min_scene_len=min_scene_frames,
                )
            )

            start_tc = FrameTimecode(
                timecode=start if start is not None else 0.0,
                fps=self.frame_rate,
            )

            end_tc = (
                FrameTimecode(
                    timecode=end,
                    fps=self.frame_rate,
                )
                if end is not None
                else None
            )

            self.video.seek(start_tc)

            scene_manager.detect_scenes(
                video=self.video,
                end_time=end_tc,
            )

            scenes = scene_manager.get_scene_list()

            return [(scene_start.get_seconds(), scene_end.get_seconds()) for scene_start, scene_end in scenes]

        except CutMindError:
            raise
        except Exception as exc:
            raise CutMindError(
                "Impossible d'exécuter PySceneDetect",
                code=ErrCode.FFMPEG,
                ctx={
                    "video_path": self.video_path,
                    "threshold": threshold,
                    "downscale": self.downscale,
                    "min_scene_len": min_scene_len,
                    "start": start,
                    "end": end,
                    "internal_error": str(exc),
                    "type": type(exc).__name__,
                },
            ) from exc
