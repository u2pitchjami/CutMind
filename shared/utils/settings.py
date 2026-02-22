"""
settings.py — Centralisation typée des paramètres YAML via dataclasses.
Doit être initialisé UNE seule fois via init_settings(config) dans main().
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ==========================================================
#               SMARTCUT — DATACLASSES
# ==========================================================


@dataclass
class SmartcutCoreSettings:
    scan_interval: int
    purge_days: int
    batch_size: int
    use_cuda: bool
    initial_threshold: int
    min_threshold: int
    threshold_step: int
    min_duration: float
    max_duration: float


@dataclass
class FFSmartcutSettings:
    vcodec: str
    preset: str
    pix_fmt: str
    crf: int
    profile: str
    profile_v: str
    color_primaries: str
    color_trc: str
    colorspace: str
    vsync: str
    tag: str
    tag_v: str
    movflags: str
    acodec: str
    audio_bitrate: str
    ar: int
    ac: int


@dataclass
class AnalyseSegmentSettings:
    max_frames_per_batch: int
    safety_margin_gb: float
    limit_tokens: int
    fps_extract: float
    base_rate: int
    precision_4bit: float
    precision_bfloat16: float
    precision_float16: float
    precision_float32: float
    precision_default: float


@dataclass
class GenerateKeywordsSettings:
    model_4b: str
    model_8b: str
    max_new_tokens: int
    min_pixels: int
    max_pixels: int
    total_pixels: int
    sizeh: int
    sizel: int
    tokenize: bool
    add_generation_prompt: bool
    padding: bool
    return_tensors: str
    temperature: float
    top_p: float
    repetition_penalty: float
    do_sample: bool
    skip_special_tokens: bool
    clean_up_tokenization_spaces: bool
    free_vram_8b: int
    free_vram_4b: int
    load_in_4bit: bool
    bnb_4bit_use_double_quant: bool
    bnb_4bit_quant_type: str
    bnb_4bit_compute_dtype: str
    load_in_4bit_4b: bool
    bnb_4bit_use_double_quant_4b: bool
    bnb_4bit_quant_type_4b: str
    bnb_4bit_compute_dtype_4b: str
    torch_dtype: str
    device_map: str
    device_map_cpu: str
    attn_implementation: str


@dataclass
class KeywordNormalizerSettings:
    model_name_key: str
    mode: str
    similarity_threshold: float


@dataclass
class AnalyseConfidenceSettings:
    model_confidence: str
    device: str


# ==========================================================
#            COMFYUI ROUTER — DATACLASSES
# ==========================================================


@dataclass
class OrchestratorSettings:
    forbidden_hours: list[int]


@dataclass
class OptimalBatchSizeSettings:
    min_size: int


@dataclass
class ProcessorSettings:
    purge_days: int
    force_deinterlace: bool
    cleanup: bool
    delta_duration: int
    ratio_duration: float


@dataclass
class WaitOutputSettings:
    stable_time: int
    check_interval: int
    timeout: int


# ==========================================================
#            CUTMIND — DATACLASSES
# ==========================================================


@dataclass
class ValidationSettings:
    normal: str
    manual: str


@dataclass
class AuditSettings:
    start: str
    end: str


# @dataclass(slots=True)
# class SegmentStatusRule:
#     all: list[str] | None = None
#     any: list[str] | None = None
#     allowed: list[str] | None = None
#     expected: list[str] | None = None


# @dataclass(slots=True)
# class VideoStatusRule:
#     segments: SegmentStatusRule


# @dataclass(slots=True)
# class StatusConsistencyRulesV2:
#     rules: dict[str, VideoStatusRule]


# @dataclass(slots=True)
# class VideoStatusPriority:
#     order: list[str]


# ==========================================================
#                 SETTINGS ROOT OBJECT
# ==========================================================


@dataclass
class Settings:
    smartcut: SmartcutCoreSettings
    ffsmartcut: FFSmartcutSettings
    analyse_segment: AnalyseSegmentSettings
    generate_keywords: GenerateKeywordsSettings
    keyword_normalizer: KeywordNormalizerSettings
    analyse_confidence: AnalyseConfidenceSettings

    router_orchestrator: OrchestratorSettings
    router_optimal_batch_size: OptimalBatchSizeSettings
    router_processor: ProcessorSettings
    router_wait_output: WaitOutputSettings

    cutmind_validation: ValidationSettings
    cutmind_audit: AuditSettings
    # cutmind_status_consistency: StatusConsistencyRulesV2
    # cutmind_video_status_priority: VideoStatusPriority

    # IMPORTANT :
    # adaptive_batch reste un dict car le code actuel utilise .get() et accès dynamiques
    adaptive_batch: dict[str, Any]


SETTINGS: Settings | None = None


# ==========================================================
#                     INITIALISATION
# ==========================================================


def init_settings(config: Any) -> None:
    """
    Initialise toutes les settings à partir des YAML chargés par ConfigManager.
    """
    global SETTINGS

    sc = config.smartcut
    rt = config.comfyui_router
    cm = config.cutmind

    SETTINGS = Settings(
        smartcut=SmartcutCoreSettings(
            scan_interval=sc["smartcut"]["scan_interval"],
            purge_days=sc["smartcut"]["purge_days"],
            batch_size=sc["smartcut"]["batch_size"],
            use_cuda=sc["smartcut"]["use_cuda"],
            initial_threshold=sc["smartcut"]["initial_threshold"],
            min_threshold=sc["smartcut"]["min_threshold"],
            threshold_step=sc["smartcut"]["threshold_step"],
            min_duration=sc["smartcut"]["min_duration"],
            max_duration=sc["smartcut"]["max_duration"],
        ),
        ffsmartcut=FFSmartcutSettings(**sc["ffsmartcut"]),
        analyse_segment=AnalyseSegmentSettings(
            max_frames_per_batch=sc["analyse_segment"]["max_frames_per_batch"],
            safety_margin_gb=sc["analyse_segment"]["safety_margin_gb"],
            limit_tokens=sc["analyse_segment"]["limit_tokens"],
            fps_extract=sc["analyse_segment"]["fps_extract"],
            base_rate=sc["analyse_segment"]["base_rate"],
            precision_4bit=sc["analyse_segment"]["4bit"],
            precision_bfloat16=sc["analyse_segment"]["bfloat16"],
            precision_float16=sc["analyse_segment"]["float16"],
            precision_float32=sc["analyse_segment"]["float32"],
            precision_default=sc["analyse_segment"]["default"],
        ),
        generate_keywords=GenerateKeywordsSettings(**sc["generate_keywords"]),
        keyword_normalizer=KeywordNormalizerSettings(**sc["keyword_normalizer"]),
        analyse_confidence=AnalyseConfidenceSettings(**sc["analyse_confidence"]),
        router_orchestrator=OrchestratorSettings(
            forbidden_hours=rt["orchestrator"]["router_forbidden_hours"],
        ),
        router_optimal_batch_size=OptimalBatchSizeSettings(min_size=rt["optimal_batch_size"]["min_size"]),
        router_processor=ProcessorSettings(**rt["processor"]),
        router_wait_output=WaitOutputSettings(**rt["wait_for_output"]),
        cutmind_validation=ValidationSettings(
            normal=cm["validation"]["normal"],
            manual=cm["validation"]["manual"],
        ),
        cutmind_audit=AuditSettings(
            start=cm["audit_window"]["start"],
            end=cm["audit_window"]["end"],
        ),
        adaptive_batch=rt["adaptive_batch"],  # ← laissé en dict volontairement
        # cutmind_status_consistency=StatusConsistencyRulesV2(
        #     rules={
        #         video_status: VideoStatusRule(segments=SegmentStatusRule(**rule["segments"]))
        #         for video_status, rule in cm["status_consistency_rules"]["rules"].items()
        #     }
        # ),
        # cutmind_video_status_priority=VideoStatusPriority(order=cm["video_status_priority"]["order"]),
    )


def get_settings() -> Settings:
    if SETTINGS is None:
        raise RuntimeError("SETTINGS non initialisé. Appeler init_settings(config).")
    return SETTINGS
