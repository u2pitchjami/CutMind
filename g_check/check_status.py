# check/check_status.py

from __future__ import annotations

from shared.models.db_models import Video
from shared.status_orchestrator.statuses import SegmentStatus, VideoStatus


def compute_video_status(video: Video) -> VideoStatus:
    """
    Calcule le statut vidéo à partir des segments (V2).

    - aucune IO
    - aucune écriture
    - aucune règle YAML
    """

    segments = video.segments
    if not segments:
        return VideoStatus.INIT

    # 1️⃣ Blocage humain CUT
    if any(s.pipeline_target == "CUT_VALIDATION" for s in segments):
        return VideoStatus.IN_CUT_VALIDATION

    # 2️⃣ Blocage humain FINAL
    if any(s.pipeline_target == "VALIDATION" for s in segments):
        return VideoStatus.IN_FINAL_VALIDATION

    # 3️⃣ Déplacement fichiers post-cut
    if any(s.pipeline_target == "TO_MOVE" for s in segments):
        return VideoStatus.POST_CUT_MOVE

    # 3️⃣ Rework IA demandé
    if any(s.pipeline_target == "IA" for s in segments):
        return VideoStatus.READY_FOR_IA

    # 4️⃣ Tous validés → fin
    if all(s.status == SegmentStatus.VALIDATED for s in segments):
        return VideoStatus.VALIDATED

    # 5️⃣ Enhancement
    if any(s.status == SegmentStatus.CUT_VALIDATED for s in segments):
        return VideoStatus.READY_FOR_ENHANCEMENT

    # 6️⃣ IA
    if any(s.status == SegmentStatus.ENHANCED for s in segments):
        return VideoStatus.READY_FOR_IA

    # 7️⃣ Confidence
    if any(s.status == SegmentStatus.IA_DONE for s in segments):
        return VideoStatus.READY_FOR_CONFIDENCE

    if all(s.status == SegmentStatus.VALIDATED_CHECK for s in segments):
        return VideoStatus.VALIDATED_CHECK

    return VideoStatus.INIT
