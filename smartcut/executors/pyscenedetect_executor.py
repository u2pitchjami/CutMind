from __future__ import annotations

from scenedetect import ContentDetector, FrameTimecode, SceneManager, open_video  # type: ignore

from shared.models.exceptions import CutMindError, ErrCode


def run_pyscenedetect(
    video_path: str,
    threshold: float,
    downscale: int = 1,
    min_scene_len: float = 15.0,
    start: float | None = None,
    end: float | None = None,
) -> list[tuple[float, float]]:
    """
    Exécute PySceneDetect en mode brut (pas de filtrage, pas de logging).
    Retourne une liste [(start_sec, end_sec)].
    """
    try:
        video = open_video(video_path)
        # video.set_downscale_factor(downscale)
        scene_manager = SceneManager()
        scene_manager.add_detector(ContentDetector(threshold=threshold, min_scene_len=int(min_scene_len)))

        start_tc = FrameTimecode(timecode=start, fps=video.frame_rate) if start else None
        end_tc = FrameTimecode(timecode=end, fps=video.frame_rate) if end else None

        if start_tc:
            video.seek(start_tc)

        # Detect all scenes in video from current position to end.
        scene_manager.detect_scenes(video, end_time=end_tc)
        # `get_scene_list` returns a list of start/end timecode pairs
        # for each scene that was found.
        scenes = scene_manager.get_scene_list()

        return [(s.get_seconds(), e.get_seconds()) for s, e in scenes]

    except Exception as exc:
        raise CutMindError(
            "Impossible d'exécuter PySceneDetect",
            code=ErrCode.FFMPEG,
            ctx={
                "video_path": video_path,
                "threshold": threshold,
                "downscale": downscale,
                "min_scene_len": min_scene_len,
                "start": start,
                "end": end,
                "internal_error": str(exc),
                "type": type(exc).__name__,
            },
        ) from exc
