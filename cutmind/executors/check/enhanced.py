# check/check_enhanced_segments.py

from pathlib import Path

from cutmind.models_cm.db_models import Segment
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.services.video_preparation import VideoPrepared


def check_segments(seg: Segment, metadata: VideoPrepared, path: Path) -> bool:
    """
    Compare les métadonnées stockées dans le Segment avec celles du fichier réel.
    Si des différences sont détectées → mise à jour du segment → return True.
    """
    updated = False
    try:
        # Mapping Segment <-> VideoPrepared
        mapping: dict[str, str] = {
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

        for seg_attr, meta_attr in mapping.items():
            seg_val = getattr(seg, seg_attr, None)
            meta_val = getattr(metadata, meta_attr, None)

            if seg_val != meta_val:
                setattr(seg, seg_attr, meta_val)
                updated = True

        return updated

    except Exception as exc:  # pylint: disable=broad-except
        raise CutMindError(
            "❌ Erreur inattendue lors de check_segments.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"seg.id": seg.id, "path": str(path)}),
        ) from exc
