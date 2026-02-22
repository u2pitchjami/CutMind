# check/check_enhanced_segments.py

from typing import Any

from shared.models.db_models import Segment
from shared.services.video_preparation import VideoPrepared
from shared.utils.config import (
    COLOR_BLUE,
    COLOR_CYAN,
    COLOR_GREEN,
    COLOR_PURPLE,
    COLOR_RESET,
    COLOR_YELLOW,
)
from shared.utils.logger import LoggerProtocol


def log_metadata_diff(
    seg: Segment,
    meta: VideoPrepared,
    logger: LoggerProtocol,
) -> None:
    """
    Log les différences techniques entre le Segment en DB
    et les métadonnées réelles (VideoPrepared).
    Seuls les champs modifiés sont affichés.
    """

    FIELD_MAP: dict[str, str] = {
        "resolution": "resolution",
        "fps": "fps",
        "duration": "duration",
        "codec": "codec",
        "bitrate": "bitrate",
        "filesize_mb": "filesize_mb",
        "nb_frames": "nb_frames",
        "has_audio": "has_audio",
        "audio_codec": "audio_codec",
        "audio_bitrate": "audio_bitrate",
        "audio_channels": "audio_channels",
        "audio_sample_rate": "audio_sample_rate",
    }

    def fmt(v: Any) -> str:
        """Formatage simple avec arrondi si float."""
        if isinstance(v, float):
            return f"{v:.2f}"
        if v is None:
            return "N/A"
        return str(v)

    logger.info(f"{COLOR_PURPLE}🧾 Diff métadonnées pour segment {COLOR_CYAN}{seg.uid}{COLOR_RESET}")

    changes_detected = False

    for seg_attr, meta_attr in FIELD_MAP.items():
        before = getattr(seg, seg_attr, None)
        after = getattr(meta, meta_attr, None)

        if before == after:
            continue  # pas de différence → on ignore

        changes_detected = True

        logger.info(
            f"{COLOR_BLUE}📌 {seg_attr:<15}{COLOR_YELLOW}{fmt(before)}"
            f"{COLOR_RESET} → {COLOR_GREEN}{fmt(after)}{COLOR_RESET}"
        )

    if not changes_detected:
        logger.info(f"{COLOR_GREEN}✔ Aucun changement détecté{COLOR_RESET}")
