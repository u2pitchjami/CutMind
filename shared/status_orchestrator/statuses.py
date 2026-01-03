class OrchestratorStatus:
    # --- SmartCut ---
    VIDEO_INIT = "init"
    VIDEO_READY_PYSCENE = "init"
    VIDEO_PYSCENE_DONE = "scenes_done"
    VIDEO_READY_FOR_CUT = "scenes_done"
    VIDEO_SMARTCUT_ERROR = "error"
    VIDEO_CUT_DONE = "cut_ok"
    SEGMENT_INIT = "raw"
    SEGMENT_CUT_DONE = "cut_ok"

    # --- Validation cuts ---
    SEGMENT_READY_FOR_CUT_VALIDATION = "cut_ok"
    SEGMENT_CUT_VALIDATED = "cut_validated"
    VIDEO_CUT_VALIDATED = "cut_validated"

    # --- Enhancement ---
    VIDEO_READY_FOR_ENHANCEMENT = "cut_validated"
    VIDEO_ENHANCED = "enhanced"
    SEGMENT_READY_FOR_ENHANCEMENT = "cut_validated"
    SEGMENT_ENHANCED = "enhanced"
    VIDEO_IN_ROUTER = "processing_router"
    SEGMENT_IN_ROUTER = "in_router"

    # --- IA ---
    VIDEO_READY_FOR_IA = "cut_ok"
    SEGMENT_READY_FOR_IA = "cut_ok"
    IA_DONE = "ia_done"

    # --- Confidence ---
    CONFIDENCE_DONE = "confidence_done"

    # --- Category validation ---
    CATEGORY_VALIDATED = "category_validated"
    SEGMENT_VALIDATED = "validated"
    VIDEO_READY_FOR_VALIDATION = "confidence_done"
    VIDEO_VALIDATED = "validated"
    SEGMENT_PENDING_CHECK = "pending_check"
    VIDEO_PENDING_CHECK = "pending_check"

    # --- Initial ---

    # --- SmartCut ---
    SCENES_DONE = "scenes_done"

    # --- Cut validation ---
    CUT_VALIDATED = "cut_validated"

    # --- Enhancement ---
    ENHANCED = "enhanced"

    # --- IA ---
    IA_DONE = "ia_done"

    # --- Confidence ---
    CONFIDENCE_DONE = "confidence_done"

    # --- Category validation ---
    CATEGORIES_VALIDATED = "category_validated"
