from __future__ import annotations

from scenedetect import (  # type: ignore
    ContentDetector,
    SceneManager,
    StatsManager,
    open_video,
)

from shared.models.exceptions import CutMindError, ErrCode
from smartcut.models.scene_analysis import SceneAnalysis

CONTENT_VALUE_KEY = "content_val"


def analyze_video(
    video_path: str,
    *,
    downscale: int = 1,
) -> SceneAnalysis:
    """
    Analyse une vidéo une seule fois avec PySceneDetect.

    Les métriques `content_val` sont conservées en mémoire dans
    un objet SceneAnalysis afin de permettre plusieurs détections
    avec différents seuils sans redécoder la vidéo.
    """
    if downscale < 1:
        raise ValueError("downscale doit être >= 1")

    try:
        video = open_video(video_path)

        fps = float(video.frame_rate)

        if fps <= 0.0:
            raise ValueError(f"Framerate invalide pour la vidéo : {fps}")

        duration = float(video.duration.get_seconds())
        frame_count = int(video.duration.get_frames())

        stats_manager = StatsManager(
            base_timecode=video.base_timecode,
        )

        scene_manager = SceneManager(
            stats_manager=stats_manager,
        )

        scene_manager.auto_downscale = False
        scene_manager.downscale = downscale

        detector = ContentDetector(
            threshold=0.0,
            min_scene_len=1,
        )

        scene_manager.add_detector(detector)

        # Une seule lecture/détection de toute la vidéo.
        scene_manager.detect_scenes(video)

        content_values: list[float | None] = []

        for frame_number in range(frame_count):
            metrics = stats_manager.get_metrics(
                frame_number,
                [CONTENT_VALUE_KEY],
            )

            raw_value = metrics[0]

            if raw_value is None:
                content_values.append(None)
                continue

            content_values.append(float(raw_value))

        return SceneAnalysis(
            fps=fps,
            duration=duration,
            content_values=tuple(content_values),
        )

    except CutMindError:
        raise

    except Exception as exc:
        raise CutMindError(
            "Impossible d'analyser la vidéo avec PySceneDetect.",
            code=ErrCode.FFMPEG,
            ctx={
                "video_path": video_path,
                "downscale": downscale,
                "internal_error": str(exc),
                "type": type(exc).__name__,
            },
        ) from exc
