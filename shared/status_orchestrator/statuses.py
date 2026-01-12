from enum import Enum


class VideoStatus(str, Enum):
    INIT = "init"
    SCENES_DONE = "scenes_done"
    CUT_OK = "cut_ok"
    CUT_VALIDATION_PENDING = "cut_validation_pending"
    CUT_VALIDATED = "cut_validated"
    ENHANCED = "enhanced"
    IA_DONE = "ia_done"
    CONFIDENCE_DONE = "confidence_done"
    VALIDATED = "validated"
    PENDING_CHECK = "pending_check"
    PROCESSING_ROUTER = "processing_router"
    PROCESSING_IA = "processing_ia"
    IN_CONFIDENCE = "in_confidence"
    ERROR = "error"
    IN_CUT_VALIDATION = "in_cut_validation"
    IN_FINAL_VALIDATION = "in_final_validation"
    READY_FOR_IA = "ready_for_ia"
    READY_FOR_ENHANCEMENT = "ready_for_enhancement"
    READY_FOR_CONFIDENCE = "ready_for_confidence"
    POST_CUT_MOVE = "post_cut_move"


class SegmentStatus(str, Enum):
    RAW = "raw"
    CUT_OK = "cut_ok"
    CUT_VALIDATED = "cut_validated"
    ENHANCED = "enhanced"
    IA_DONE = "ia_done"
    CONFIDENCE_DONE = "confidence_done"
    VALIDATED = "validated"
    PENDING_CHECK_VALIDATION = "VALIDATION"
    PENDING_CHECK_CUT = "CUT_VALIDATION"
    IN_ROUTER = "in_router"
    PROCESSING_IA = "processing_ia"
    IN_CONFIDENCE = "in_confidence"
    TO_MOVE = "to_move"
    TO_IA = "IA"


class OrchestratorStatus:
    # --- SmartCut ---
    VIDEO_INIT = VideoStatus.INIT
    VIDEO_READY_PYSCENE = VideoStatus.INIT
    VIDEO_PYSCENE_DONE = VideoStatus.SCENES_DONE
    VIDEO_READY_FOR_CUT = VideoStatus.SCENES_DONE
    VIDEO_SMARTCUT_ERROR = VideoStatus.ERROR
    VIDEO_CUT_DONE = VideoStatus.CUT_OK

    SEGMENT_INIT = SegmentStatus.RAW
    SEGMENT_CUT_DONE = SegmentStatus.CUT_OK

    # --- Validation cuts ---
    VIDEO_READY_FOR_CUT_VALIDATION = VideoStatus.CUT_OK
    SEGMENT_IN_CUT_VALIDATION = SegmentStatus.PENDING_CHECK_CUT
    SEGMENT_CUT_VALIDATED = SegmentStatus.CUT_VALIDATED
    SEGMENT_TO_MOVE = SegmentStatus.TO_MOVE
    VIDEO_CUT_VALIDATED = VideoStatus.CUT_VALIDATED

    # --- Enhancement ---
    VIDEO_READY_FOR_ENHANCEMENT = VideoStatus.CUT_VALIDATED
    VIDEO_ENHANCED = VideoStatus.ENHANCED
    SEGMENT_ENHANCED = SegmentStatus.ENHANCED

    # --- IA ---
    VIDEO_READY_FOR_IA = VideoStatus.ENHANCED
    VIDEO_IA_DONE = VideoStatus.IA_DONE
    SEGMENT_IA_DONE = SegmentStatus.IA_DONE
    SEGMENT_TO_IA = SegmentStatus.TO_IA

    # --- Confidence ---
    VIDEO_READY_FOR_CONFIDENCE = VideoStatus.IA_DONE
    VIDEO_CONFIDENCE_DONE = VideoStatus.CONFIDENCE_DONE
    SEGMENT_CONFIDENCE_DONE = SegmentStatus.CONFIDENCE_DONE

    # --- Category validation ---
    CATEGORY_VALIDATED = VideoStatus.VALIDATED
    SEGMENT_VALIDATED = SegmentStatus.VALIDATED
    VIDEO_READY_FOR_VALIDATION = VideoStatus.CONFIDENCE_DONE
    VIDEO_VALIDATED = VideoStatus.VALIDATED
    SEGMENT_PENDING_CHECK = SegmentStatus.PENDING_CHECK_VALIDATION
    VIDEO_PENDING_CHECK = VideoStatus.PENDING_CHECK
