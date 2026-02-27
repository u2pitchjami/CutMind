from pathlib import Path
import subprocess

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.settings import get_settings

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
    Fixe une résolution non standard en ciblant 1920x1080 ou 3840x2160.

    Garantit une résolution finale paire (codec-safe). Respecte le profil interne CutMind.
    """
    settings = get_settings()

    PRESET: str = settings.ffsmartcut.preset
    VCODEC: str = settings.ffsmartcut.vcodec
    CRF: int = settings.ffsmartcut.crf
    PIX_FMT: str = settings.ffsmartcut.pix_fmt
    PROFILE: str = settings.ffsmartcut.profile
    COLOR_PRIMARIES: str = settings.ffsmartcut.color_primaries
    COLOR_TRC: str = settings.ffsmartcut.color_trc
    COLORSPACE: str = settings.ffsmartcut.colorspace
    VSYNC: str = settings.ffsmartcut.vsync
    TAG: str = settings.ffsmartcut.tag
    MOVFLAGS: str = settings.ffsmartcut.movflags
    ACODEC: str = settings.ffsmartcut.acodec
    AUDIO_BITRATE: str = settings.ffsmartcut.audio_bitrate
    AR: int = settings.ffsmartcut.ar
    AC: int = settings.ffsmartcut.ac

    try:
        if is_close(input_res, STANDARD_2160P):
            target = STANDARD_2160P
        else:
            target = STANDARD_1080P

        if input_res[0] < target[0] or input_res[1] < target[1]:
            vf = (
                f"scale={target[0]}:{target[1]}:force_original_aspect_ratio=decrease,"
                f"pad={target[0]}:{target[1]}:(ow-iw)/2:(oh-ih)/2,"
                f"scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1"
            )
        else:
            vf = f"crop={target[0]}:{target[1]},scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1"

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(in_path),
            "-vf",
            vf,
            "-c:v",
            VCODEC,
            "-preset",
            PRESET,
            "-crf",
            str(CRF),
            "-pix_fmt",
            PIX_FMT,
            "-profile:v",
            PROFILE,
            "-color_primaries",
            COLOR_PRIMARIES,
            "-color_trc",
            COLOR_TRC,
            "-colorspace",
            COLORSPACE,
            "-vsync",
            VSYNC,
            "-tag:v",
            TAG,
            "-movflags",
            MOVFLAGS,
            "-c:a",
            ACODEC,
            "-b:a",
            AUDIO_BITRATE,
            "-ar",
            str(AR),
            "-ac",
            str(AC),
            str(out_path),
        ]

        subprocess.run(cmd, check=True)
        return target

    except subprocess.CalledProcessError as exc:
        raise CutMindError(
            "❌ Erreur FFMPEG fix_segment_resolution.",
            code=ErrCode.FFMPEG,
            ctx=get_step_ctx({"video_path": str(in_path)}),
        ) from exc

    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors du fix_segment_resolution.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video_path": str(in_path)}),
        ) from exc
