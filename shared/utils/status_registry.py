class VideoStatusKey:
    # Initial
    INIT = "init"

    # SmartCut
    SCENES_OK = "scenes_ok"
    CUT_OK = "cut_ok"

    # Enhancement
    ENHANCED = "enhanced"

    # IA
    IA_READY = "ia_ready"
    IA_DONE = "ia_done"

    # Validation
    CONFIDENCE_DONE = "confidence_done"
    CATEGORIES_VALIDATED = "categories_validated"


class SegmentStatusKey:
    # Creation
    RAW = "raw"

    # Cut
    CUT_OK = "cut_ok"

    # Validation
    CUT_VALIDATED = "cut_validated"

    # Enhancement
    ENHANCED = "enhanced"

    # IA
    IA_DONE = "ia_done"

    # Category validation
    CONFIDENCE_DONE = "confidence_done"
    CATEGORY_VALIDATED = "category_validated"


class FlowGate:
    # IA
    IA_VIDEO_INPUT = "cut_ok"
    IA_SEGMENT_INPUT = "cut_ok"

    # Enhancement
    COMFYUI_VIDEO_INPUT = "cut_validated"

    # Validation
    CATEGORY_VALIDATION_INPUT = "ia_done"
