class OrchestratorStatus:
    # --- SmartCut ---
    VIDEO_READY_FOR_CUT = "init"
    VIDEO_CUT_DONE = "scenes_done"

    # --- Validation cuts ---
    SEGMENT_READY_FOR_CUT_VALIDATION = "raw"
    SEGMENT_CUT_VALIDATED = "cut_validated"

    # --- Enhancement ---
    VIDEO_READY_FOR_ENHANCEMENT = "cut_validated"
    VIDEO_ENHANCED = "enhanced"

    # --- IA ---
    VIDEO_READY_FOR_IA = "cut_ok"
    SEGMENT_READY_FOR_IA = "cut_ok"
    IA_DONE = "ia_done"

    # --- Confidence ---
    CONFIDENCE_DONE = "confidence_done"

    # --- Category validation ---
    CATEGORY_VALIDATED = "category_validated"
