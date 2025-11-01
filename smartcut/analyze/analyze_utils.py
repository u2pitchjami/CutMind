""" """

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from shared.models.config_manager import CONFIG
from shared.models.smartcut_model import SmartCutSession
from shared.utils.config import TMP_FRAMES_DIR_SC
from shared.utils.logger import get_logger
from smartcut.norm_keywords.keyword_normalizer import KeywordNormalizer

logger = get_logger(__name__)

QBIT = CONFIG.smartcut["analyse_segment"]["4bit"]
BFLOAT16 = CONFIG.smartcut["analyse_segment"]["bfloat16"]
FLOAT16 = CONFIG.smartcut["analyse_segment"]["float16"]
FLOAT32 = CONFIG.smartcut["analyse_segment"]["float32"]
DEFAULT = CONFIG.smartcut["analyse_segment"]["default"]


def estimate_safe_batch_size(
    free_vram_gb: float,
    model_precision: str = "4bit",  # "bfloat16", "float16", etc.
    safety_margin_gb: float = 1.0,
) -> int:
    """
    Estime dynamiquement un batch size sûr en fonction de la VRAM libre.
    """
    # Estimations empiriques à adapter si besoin
    est_mem_per_image = {
        "4bit": QBIT,
        "bfloat16": BFLOAT16,
        "float16": FLOAT16,
        "float32": FLOAT32,
    }.get(model_precision, DEFAULT)

    usable_vram = max(0, free_vram_gb - safety_margin_gb)
    batch_size = int(usable_vram / est_mem_per_image)
    return max(1, batch_size)


def compute_num_frames(segment_duration: float, base_rate: int = 5) -> int:
    """
    Compute number of frames to extract dynamically.

    - base_rate: number of frames per minute of video.
    - Minimum 3 frames per segment.
    """
    frames = max(3, int(base_rate * (segment_duration / 60)))
    logger.debug(f"({base_rate} * ({segment_duration} / 60) : {frames}")
    return frames


def merge_keywords_across_batches(keyword_lists: list[str]) -> str:
    """
    Fusionne plusieurs listes de mots-clés locales sans IA.

    Supprime les doublons et trie les mots.
    """
    all_keywords = []
    for klist in keyword_lists:
        for kw in klist.split(","):
            clean_kw = kw.strip().lower()
            if clean_kw:
                all_keywords.append(clean_kw)

    unique_sorted = sorted(set(all_keywords))
    return ", ".join(unique_sorted)


def delete_frames(path: Path = Path(TMP_FRAMES_DIR_SC)) -> None:
    for file in Path(path).glob("*.jpg"):
        # logger.debug(f"🧹 Vérifié : {file.name}")
        try:
            file.unlink()
            # logger.debug(f"🧹 Supprimé : {file.name}")
        except Exception as e:
            logger.warning(f"⚠️ Impossible de supprimer {file.name} : {e}")


def update_session_keywords(
    session: SmartCutSession,
    start: float,
    end: float,
    keywords_list: list[str],
) -> None:
    for segment in session.segments:
        if abs(segment.start - start) < 0.01 and abs(segment.end - end) < 0.01:
            normalizer = KeywordNormalizer(mode="mixed")
            keywords_norm = normalizer.normalize_keywords(keywords_list)

            logger.info(f"{keywords_list} → {keywords_norm}")
            segment.keywords = keywords_norm
            segment.ai_status = "done"
            SmartCutSession.last_updated = datetime.now().isoformat()

            session.save()
            logger.debug(
                f"💾 Sauvegarde JSON : segment {segment.id} "
                f"({start:.1f}s → {end:.1f}s) [{len(keywords_norm)} mots-clés]"
            )
            break
