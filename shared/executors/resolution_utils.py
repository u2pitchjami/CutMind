""" """

from __future__ import annotations

from pathlib import Path

from shared.ffmpegjob.ffjob import FFmpegJob, run_ffmpeg_job
from shared.utils.logger import LoggerProtocol

# --- Constants ---
STANDARD_1080P = (1920, 1080)
STANDARD_2160P = (3840, 2160)


# --- Resolution helpers ---
def is_close(res: tuple[int, int], target: tuple[int, int], tolerance: int = 10) -> bool:
    return abs(res[0] - target[0]) <= tolerance and abs(res[1] - target[1]) <= tolerance


def is_resolution_accepted(res: tuple[int, int]) -> bool:
    return is_close(res, STANDARD_1080P, 10) or is_close(res, STANDARD_2160P, 10)


def fix_segment_resolution(
    in_path: str | Path,
    out_path: str | Path,
    input_res: tuple[int, int],
    has_audio: bool,
    logger: LoggerProtocol | None = None,
) -> tuple[int, int]:
    """
    Fixe une résolution non standard en ciblant 1920x1080 ou 3840x2160.

    Garantit une résolution finale paire et respecte le profil interne CutMind.
    """

    input_path = Path(in_path)
    output_path = Path(out_path)

    if is_close(input_res, STANDARD_2160P):
        target = STANDARD_2160P
    else:
        target = STANDARD_1080P

    if input_res[0] < target[0] or input_res[1] < target[1]:
        video_filter = (
            f"scale={target[0]}:{target[1]}:force_original_aspect_ratio=decrease,"
            f"pad={target[0]}:{target[1]}:(ow-iw)/2:(oh-ih)/2,"
            "scale=trunc(iw/2)*2:trunc(ih/2)*2,"
            "setsar=1"
        )
    else:
        video_filter = f"crop={target[0]}:{target[1]},scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1"

    run_ffmpeg_job(
        FFmpegJob(
            step="fix_segment_resolution",
            input_path=input_path,
            output_path=output_path,
            include_audio=has_audio,
            video_filters=[video_filter],
        ),
        logger=logger,
    )

    return target
