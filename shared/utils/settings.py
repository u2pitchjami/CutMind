"""
settings.py — Centralisation typée des paramètres YAML via dataclasses.

Doit être initialisé UNE seule fois via init_settings(config) dans main().
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
from typing import Any
from urllib.parse import urlparse

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
    encoder: str
    vcodec: str
    preset: str
    pix_fmt: str
    crf: int
    quality: int
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
    min_frames_per_batch: int
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
    backend: str = "transformers"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = ""
    ollama_timeout: float = 180.0
    ollama_think: bool = False
    ollama_num_ctx: int = 16384
    ollama_batch_size: int = 6
    ollama_keep_alive: str = "1m"

    def __post_init__(self) -> None:
        # Le .env est chargé par shared.utils.config au démarrage.
        self.backend = os.getenv("KEYWORDS_BACKEND", self.backend).strip().lower()
        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", self.ollama_base_url).strip().rstrip("/")
        self.ollama_model = os.getenv("OLLAMA_MODEL", self.ollama_model).strip()
        self.ollama_timeout = float(os.getenv("OLLAMA_TIMEOUT", str(self.ollama_timeout)))
        raw_think = os.getenv("OLLAMA_THINK")
        if raw_think is not None:
            normalized_think = raw_think.strip().lower()
            if normalized_think not in {"true", "false", "1", "0", "yes", "no"}:
                raise ValueError("OLLAMA_THINK doit valoir true ou false.")
            self.ollama_think = normalized_think in {"true", "1", "yes"}
        self.ollama_num_ctx = int(os.getenv("OLLAMA_NUM_CTX", str(self.ollama_num_ctx)))
        self.ollama_batch_size = int(os.getenv("OLLAMA_BATCH_SIZE", str(self.ollama_batch_size)))
        self.ollama_keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", self.ollama_keep_alive).strip()
        if self.backend not in {"transformers", "ollama"}:
            raise ValueError("KEYWORDS_BACKEND doit valoir transformers ou ollama.")
        if self.backend == "ollama":
            url = urlparse(self.ollama_base_url)
            if url.scheme not in {"http", "https"} or not url.netloc or url.query or url.fragment:
                raise ValueError("OLLAMA_BASE_URL doit être une URL HTTP(S) sans query ni fragment.")
            if not self.ollama_model:
                raise ValueError("OLLAMA_MODEL est requis avec le moteur ollama (modèle vision).")
            if not math.isfinite(self.ollama_timeout) or self.ollama_timeout <= 0:
                raise ValueError("OLLAMA_TIMEOUT doit être strictement positif et fini.")
            if self.ollama_num_ctx < 1:
                raise ValueError("OLLAMA_NUM_CTX doit être supérieur ou égal à 1.")
            if self.ollama_batch_size < 1:
                raise ValueError("OLLAMA_BATCH_SIZE doit être supérieur ou égal à 1.")


@dataclass
class KeywordNormalizerSettings:
    model_name_key: str
    mode: str
    similarity_threshold: float
    backend: str = "transformers"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = ""
    ollama_timeout: float = 180.0
    ollama_keep_alive: str = "1m"

    def __post_init__(self) -> None:
        self.backend = os.getenv("KEYWORD_NORMALIZER_BACKEND", self.backend).strip().lower()
        self.ollama_base_url = (
            os.getenv("KEYWORD_NORMALIZER_OLLAMA_BASE_URL", os.getenv("OLLAMA_BASE_URL", self.ollama_base_url))
            .strip()
            .rstrip("/")
        )
        self.ollama_model = os.getenv("KEYWORD_NORMALIZER_OLLAMA_MODEL", self.ollama_model).strip()
        self.ollama_timeout = float(os.getenv("KEYWORD_NORMALIZER_OLLAMA_TIMEOUT", str(self.ollama_timeout)))
        self.ollama_keep_alive = os.getenv("KEYWORD_NORMALIZER_OLLAMA_KEEP_ALIVE", self.ollama_keep_alive).strip()
        if self.backend not in {"transformers", "ollama"}:
            raise ValueError("KEYWORD_NORMALIZER_BACKEND doit valoir transformers ou ollama.")
        if self.backend == "ollama":
            url = urlparse(self.ollama_base_url)
            if url.scheme not in {"http", "https"} or not url.netloc or url.query or url.fragment:
                raise ValueError("KEYWORD_NORMALIZER_OLLAMA_BASE_URL doit être une URL HTTP(S) sans query ni fragment.")
            if not self.ollama_model:
                raise ValueError("KEYWORD_NORMALIZER_OLLAMA_MODEL est requis (modèle d'embeddings).")
            if not math.isfinite(self.ollama_timeout) or self.ollama_timeout <= 0:
                raise ValueError("KEYWORD_NORMALIZER_OLLAMA_TIMEOUT doit être strictement positif et fini.")


@dataclass
class AnalyseConfidenceSettings:
    model_confidence: str
    device: str
    backend: str = "transformers"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = ""
    ollama_timeout: float = 180.0
    ollama_keep_alive: str = "1m"

    def __post_init__(self) -> None:
        self.backend = os.getenv("CONFIDENCE_BACKEND", self.backend).strip().lower()
        self.ollama_base_url = (
            os.getenv("CONFIDENCE_OLLAMA_BASE_URL", os.getenv("OLLAMA_BASE_URL", self.ollama_base_url))
            .strip()
            .rstrip("/")
        )
        self.ollama_model = os.getenv("CONFIDENCE_OLLAMA_MODEL", self.ollama_model).strip()
        self.ollama_timeout = float(os.getenv("CONFIDENCE_OLLAMA_TIMEOUT", str(self.ollama_timeout)))
        self.ollama_keep_alive = os.getenv("CONFIDENCE_OLLAMA_KEEP_ALIVE", self.ollama_keep_alive).strip()
        if self.backend not in {"transformers", "ollama"}:
            raise ValueError("CONFIDENCE_BACKEND doit valoir transformers ou ollama.")
        if self.backend == "ollama":
            url = urlparse(self.ollama_base_url)
            if url.scheme not in {"http", "https"} or not url.netloc or url.query or url.fragment:
                raise ValueError("CONFIDENCE_OLLAMA_BASE_URL doit être une URL HTTP(S) sans query ni fragment.")
            if not self.ollama_model:
                raise ValueError("CONFIDENCE_OLLAMA_MODEL est requis (modèle d'embeddings).")
            if not math.isfinite(self.ollama_timeout) or self.ollama_timeout <= 0:
                raise ValueError("CONFIDENCE_OLLAMA_TIMEOUT doit être strictement positif et fini.")


# ==========================================================
#            COMFYUI ROUTER — DATACLASSES
# ==========================================================


@dataclass
class OrchestratorSettings:
    forbidden_hours: list[int]
    smartcut: bool
    cut: bool
    move_post_cut: bool
    enhancement: bool
    IA: bool
    confidence: bool
    validation: bool
    final_check: bool


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
    keep_temp_files: bool
    realesrgan_model: str
    rife_model: str
    g_param: int
    j_param: str
    target_width: int
    target_height: int
    target_fps: int
    target_aspect_ratio: str
    upscale_ratio: int
    upscale_ratio_up: str
    upscale_ratio_down: str


@dataclass
class InterpolationSettings:
    cfr_threshold_ratio: float
    ffmpeg_threshold_ratio: float
    method_low_fps: str
    method_mid_fps: str
    method_high_fps: str


@dataclass
class WaitOutputSettings:
    stable_time: int
    check_interval: int
    timeout: int


# ==========================================================
#            CUTMIND — DATACLASSES
# ==========================================================


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
    router_interpolation: InterpolationSettings
    router_wait_output: WaitOutputSettings

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
    er = config.enhancer_router

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
            min_frames_per_batch=sc["analyse_segment"]["min_frames_per_batch"],
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
            forbidden_hours=er["orchestrator"]["router_forbidden_hours"],
            smartcut=er["orchestrator"]["smartcut"],
            cut=er["orchestrator"]["cut"],
            move_post_cut=er["orchestrator"]["move_post_cut"],
            enhancement=er["orchestrator"]["enhancement"],
            IA=er["orchestrator"]["IA"],
            confidence=er["orchestrator"]["confidence"],
            validation=er["orchestrator"]["validation"],
            final_check=er["orchestrator"]["final_check"],
        ),
        router_optimal_batch_size=OptimalBatchSizeSettings(min_size=rt["optimal_batch_size"]["min_size"]),
        router_processor=ProcessorSettings(**er["processor"]),
        router_interpolation=InterpolationSettings(**er["interpolation"]),
        router_wait_output=WaitOutputSettings(**rt["wait_for_output"]),
        adaptive_batch=rt["adaptive_batch"],  # ← laissé en dict volontairement
    )


def get_settings() -> Settings:
    if SETTINGS is None:
        raise RuntimeError("SETTINGS non initialisé. Appeler init_settings(config).")
    return SETTINGS
