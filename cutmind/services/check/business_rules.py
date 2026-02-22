from enum import Enum

from cutmind.models_cm.db_models import Segment
from shared.models.videoprep import VideoPrepared


class BusinessAction(str, Enum):
    NONE = "none"
    TRASH = "trash"
    SEND_TO_IA = "send_to_ia"
    FIX_METADATA = "fix_metadata"
    WARNING_ONLY = "warning_only"


def evaluate_segment_business_rules(
    segment: Segment,
    metadata: VideoPrepared,
    min_duration: float = 1.5,
    max_duration: float = 240.0,
) -> tuple[str, str, BusinessAction]:
    """
    Vérifie les règles métier sur un segment.
    Retourne: (status, message, action)
    """

    warnings = []

    file_duration = float(metadata.duration)
    db_duration = float(segment.duration or 0)

    # 1️⃣ Segment trop court
    if file_duration < min_duration:
        return (
            "error",
            f"Segment trop court ({file_duration:.2f}s)",
            BusinessAction.TRASH,
        )

    # 2️⃣ Segment trop long
    if file_duration > max_duration:
        warnings.append(f"Segment long ({file_duration:.2f}s)")

    # 3️⃣ Absence IA
    if not segment.category or not segment.keywords:
        return (
            "error",
            "Absence category ou keywords → renvoi IA",
            BusinessAction.SEND_TO_IA,
        )

    # 4️⃣ Incohérence durée BDD
    if abs(file_duration - db_duration) > 0.3:
        return (
            "error",
            f"Durée incohérente BDD ({db_duration}) vs fichier ({file_duration})",
            BusinessAction.FIX_METADATA,
        )

    if warnings:
        return (
            "ok",
            ", ".join(warnings),
            BusinessAction.WARNING_ONLY,
        )

    return ("ok", "Segment conforme métier", BusinessAction.NONE)
