from __future__ import annotations

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from smartcut.services.scene_split.detector_service import detect_initial_scenes


def refine_long_segments(
    video_path: str,
    scenes: list[tuple[float, float]],
    thresholds: list[int],
    min_duration: float,
    max_duration: float,
) -> list[tuple[float, float]]:
    """
    Raffinage récursif des segments trop longs.
    Version pure, sans logs.
    """
    refined: list[tuple[float, float]] = []

    try:
        for start, end in scenes:
            duration = end - start

            # court → on garde
            if duration < 0.8 * max_duration:
                refined.append((start, end))
                continue

            # boucle de seuils descendants
            sub_scenes: list[tuple[float, float]] = []
            for t in thresholds:
                sub_scenes = detect_initial_scenes(
                    video_path=video_path,
                    threshold=t,
                    downscale_factor=1,
                    start=start,
                    end=end,
                    min_scene_len=min_duration,
                )
                if sub_scenes:
                    break

            # rien trouvé → garder brut
            if not sub_scenes:
                refined.append((start, end))
                continue

            # raffiner récursivement si encore trop long
            for s, e in sub_scenes:
                if (e - s) > max_duration and len(thresholds) > 1:
                    refined.extend(
                        refine_long_segments(
                            video_path,
                            [(s, e)],
                            thresholds[1:],
                            min_duration,
                            max_duration,
                        )
                    )
                else:
                    refined.append((s, e))

        return sorted(refined, key=lambda x: x[0])
    except CutMindError as err:
        raise err.with_context(get_step_ctx({"video_path": video_path})) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur lors de la détection de scènes : refine.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video_path": video_path}),
        ) from exc
