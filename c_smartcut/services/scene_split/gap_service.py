from __future__ import annotations

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx


def fill_missing_segments(
    scenes: list[tuple[float, float]],
    video_duration: float,
) -> list[tuple[float, float]]:
    """
    Ajoute des segments "gaps".
    Version pure (pas de logger).
    """
    try:
        if not scenes:
            return [(0.0, video_duration)]

        scenes = sorted(set(scenes), key=lambda x: x[0])
        filled: list[tuple[float, float]] = []

        # gap avant la première scène
        if scenes[0][0] > 0.5:
            filled.append((0.0, scenes[0][0]))

        # gaps entre scènes
        for i in range(len(scenes) - 1):
            end_current = scenes[i][1]
            start_next = scenes[i + 1][0]
            if start_next - end_current > 0.5:
                filled.append((end_current, start_next))

        # gap final
        if video_duration - scenes[-1][1] > 0.5:
            filled.append((scenes[-1][1], video_duration))

        return sorted(scenes + filled, key=lambda x: x[0])

    except Exception as exc:
        raise CutMindError(
            "❌ Erreur lors de la détection de scènes.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx(),
        ) from exc
