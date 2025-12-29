from pathlib import Path
import subprocess

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx

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
) -> tuple[int, int]:
    """
    Fixe une résolution non standard en ciblant 1920x1080 ou 3840x2160 si proche.
    Upscale + pad si trop petit, sinon crop au centre.
    """
    try:
        if is_close(input_res, STANDARD_2160P):
            target = STANDARD_2160P
        else:
            target = STANDARD_1080P

        if input_res[0] < target[0] or input_res[1] < target[1]:
            vf = (
                f"scale={target[0]}:{target[1]}:force_original_aspect_ratio=decrease,"
                f"pad={target[0]}:{target[1]}:(ow-iw)/2:(oh-ih)/2"
            )
        else:
            vf = f"crop={target[0]}:{target[1]}"

        cmd = ["ffmpeg", "-y", "-i", str(in_path), "-vf", vf, "-c:a", "copy", str(out_path)]

        subprocess.run(cmd, check=True)
        return target

    except subprocess.CalledProcessError as e:
        raise CutMindError(
            "❌ Erreur FFMPEG fix_segment_resolution.",
            code=ErrCode.FFMPEG,
            ctx=get_step_ctx({"video_path": str(in_path)}),
        ) from e
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors du fix_segment_resolution.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video_path": str(in_path)}),
        ) from exc
