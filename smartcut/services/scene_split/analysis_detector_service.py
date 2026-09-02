from __future__ import annotations

from smartcut.models.scene_analysis import SceneAnalysis


def find_candidate_cuts(
    analysis: SceneAnalysis,
    *,
    threshold: float,
    start: float = 0.0,
    end: float | None = None,
) -> list[int]:
    """
    Détecte les pics de content_val dépassant le seuil.

    Plusieurs frames consécutives au-dessus du seuil sont considérées
    comme un seul événement de transition. La frame ayant le score
    maximal est conservée.
    """
    actual_end = end if end is not None else analysis.duration

    if start < 0.0:
        raise ValueError("start doit être >= 0")

    if actual_end <= start:
        raise ValueError("end doit être supérieur à start")

    start_frame = max(
        0,
        analysis.seconds_to_frame(start),
    )

    end_frame = min(
        analysis.frame_count,
        analysis.seconds_to_frame(actual_end),
    )

    candidate_cuts: list[int] = []

    peak_frame: int | None = None
    peak_score = float("-inf")

    for frame_number in range(start_frame, end_frame):
        score = analysis.content_values[frame_number]

        if score is not None and score >= threshold:
            if score > peak_score:
                peak_score = score
                peak_frame = frame_number

            continue

        if peak_frame is not None:
            candidate_cuts.append(peak_frame)

            peak_frame = None
            peak_score = float("-inf")

    if peak_frame is not None:
        candidate_cuts.append(peak_frame)

    return candidate_cuts


def filter_cuts_by_min_duration(
    cuts: list[int],
    *,
    fps: float,
    min_duration: float,
) -> list[int]:
    """
    Filtre les cuts trop proches.

    Cette première version conserve le premier cut puis ignore
    les cuts situés à moins de min_duration du précédent.
    """
    if fps <= 0.0:
        raise ValueError("fps doit être > 0")

    if min_duration < 0.0:
        raise ValueError("min_duration doit être >= 0")

    if not cuts:
        return []

    min_frames = max(
        1,
        round(min_duration * fps),
    )

    filtered: list[int] = [cuts[0]]

    for frame_number in cuts[1:]:
        if frame_number - filtered[-1] >= min_frames:
            filtered.append(frame_number)

    return filtered


def cuts_to_segments(
    cuts: list[int],
    *,
    analysis: SceneAnalysis,
    start: float,
    end: float,
) -> list[tuple[float, float]]:
    """
    Transforme des numéros de frames de cuts en segments temporels.
    """
    if end <= start:
        raise ValueError("end doit être supérieur à start")

    if not cuts:
        return []

    boundaries: list[float] = [start]

    boundaries.extend(analysis.frame_to_seconds(frame_number) for frame_number in cuts)

    boundaries.append(end)

    segments: list[tuple[float, float]] = []

    for index in range(len(boundaries) - 1):
        segment_start = boundaries[index]
        segment_end = boundaries[index + 1]

        if segment_end <= segment_start:
            continue

        segments.append((segment_start, segment_end))

    return segments


def detect_scenes_from_analysis(
    analysis: SceneAnalysis,
    *,
    threshold: float,
    min_duration: float,
    start: float = 0.0,
    end: float | None = None,
) -> list[tuple[float, float]]:
    """Détecte les scènes uniquement à partir des métriques en RAM."""
    actual_end = end if end is not None else analysis.duration

    candidate_cuts = find_candidate_cuts(
        analysis,
        threshold=threshold,
        start=start,
        end=actual_end,
    )

    filtered_cuts = filter_cuts_by_min_duration(
        candidate_cuts,
        fps=analysis.fps,
        min_duration=min_duration,
    )

    if not filtered_cuts:
        return []

    return cuts_to_segments(
        filtered_cuts,
        analysis=analysis,
        start=start,
        end=actual_end,
    )
