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


def filter_cuts_by_min_duration(
    cuts: list[int],
    *,
    start_frame: int,
    end_frame: int,
    fps: float,
    min_duration: float,
) -> list[int]:
    """
    Filtre les cuts afin que les segments produits respectent
    la durée minimale demandée.

    Vérifie la distance :
    - entre le début du segment et le premier cut ;
    - entre deux cuts successifs ;
    - entre le dernier cut et la fin du segment.

    Les cuts sont supposés triés par numéro de frame.
    """
    if fps <= 0.0:
        raise ValueError("fps doit être > 0")

    if min_duration < 0.0:
        raise ValueError("min_duration doit être >= 0")

    if start_frame < 0:
        raise ValueError("start_frame doit être >= 0")

    if end_frame <= start_frame:
        raise ValueError("end_frame doit être supérieur à start_frame")

    if not cuts:
        return []

    min_frames = max(
        1,
        round(min_duration * fps),
    )

    filtered: list[int] = []

    for frame_number in cuts:
        # Sécurité : ignorer tout cut hors du segment courant.
        if frame_number <= start_frame:
            continue

        if frame_number >= end_frame:
            continue

        # Le premier cut doit être suffisamment éloigné
        # du début du segment.
        previous_boundary = filtered[-1] if filtered else start_frame

        if frame_number - previous_boundary < min_frames:
            continue

        filtered.append(frame_number)

    # Le dernier cut doit également laisser un segment final
    # d'au moins min_duration.
    #
    # Plusieurs suppressions peuvent être nécessaires si les
    # derniers cuts sont proches de la borne de fin.
    while filtered and end_frame - filtered[-1] < min_frames:
        filtered.pop()

    return filtered


def detect_scenes_from_analysis(
    analysis: SceneAnalysis,
    *,
    threshold: float,
    min_duration: float,
    start: float = 0.0,
    end: float | None = None,
) -> list[tuple[float, float]]:
    """
    Détecte les scènes uniquement à partir des métriques déjà
    présentes en RAM.

    Les cuts retenus doivent respecter min_duration par rapport :
    - au début du segment ;
    - aux autres cuts ;
    - à la fin du segment.
    """
    actual_end = end if end is not None else analysis.duration

    if start < 0.0:
        raise ValueError("start doit être >= 0")

    if actual_end <= start:
        raise ValueError("end doit être supérieur à start")

    candidate_cuts = find_candidate_cuts(
        analysis,
        threshold=threshold,
        start=start,
        end=actual_end,
    )

    if not candidate_cuts:
        return []

    start_frame = max(
        0,
        analysis.seconds_to_frame(start),
    )

    end_frame = min(
        analysis.frame_count,
        analysis.seconds_to_frame(actual_end),
    )

    filtered_cuts = filter_cuts_by_min_duration(
        candidate_cuts,
        start_frame=start_frame,
        end_frame=end_frame,
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
