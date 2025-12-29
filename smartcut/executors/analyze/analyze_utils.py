""" """

from __future__ import annotations

from pathlib import Path
import re

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.config import TMP_FRAMES_DIR_SC
from shared.utils.settings import get_settings
from smartcut.models_sc.ai_result import AIResult
from smartcut.services.keyword_normalizer import KeywordNormalizer

settings = get_settings()

QBIT = settings.analyse_segment.precision_4bit
BFLOAT16 = settings.analyse_segment.precision_bfloat16
FLOAT16 = settings.analyse_segment.precision_float16
FLOAT32 = settings.analyse_segment.precision_float32
DEFAULT = settings.analyse_segment.precision_default


def extract_keywords_from_filename(filename: str | Path) -> list[str]:
    """
    Extrait automatiquement des mots-clés à partir du nom de fichier.
    Exemple :
        'voyage_-_New_York_-_chouette.mp4' → ['voyage', 'New York', 'chouette']
    """
    try:
        # Nom de base sans extension
        name = Path(filename).stem

        # 1️⃣ Normalisation : remplacer underscores et tirets doubles par des espaces/tirets simples
        name = name.replace("_-_", "-").replace("_", " ")

        # 2️⃣ Séparer sur les tirets
        parts = [p.strip() for p in name.split("-") if p.strip()]

        # 3️⃣ Nettoyage : retirer caractères spéciaux ou résidus (parenthèses, points, etc.)
        clean_parts = [re.sub(r"[^a-zA-Z0-9éèàùçâêîôûÉÈÀÙÇÂÊÎÔÛ' ]", "", p).strip() for p in parts]

        # 4️⃣ Filtrer : supprimer les chaînes vides ou purement numériques
        filtered_parts = [p for p in clean_parts if p and not p.isdigit()]

        # 5️⃣ Éliminer doublons et chaînes vides
        unique_keywords = list({kw for kw in filtered_parts if kw})

        return unique_keywords
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors de l'extraction des mots clés du fichier'.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"filename": filename}),
        ) from exc


def estimate_safe_batch_size(
    free_vram_gb: float,
    total_vram_gb: float,
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
    batch_size = max(1, int(usable_vram / est_mem_per_image))

    return batch_size


def compute_num_frames(segment_duration: float, base_rate: int = 5) -> int:
    """
    Compute number of frames to extract dynamically.

    - base_rate: number of frames per minute of video.
    - Minimum 3 frames per segment.
    """
    frames = max(3, int(base_rate * (segment_duration / 60)))
    return frames


def merge_keywords_across_batches(
    batch_outputs: list[AIResult],
    normalizer: KeywordNormalizer | None = None,
) -> tuple[str, list[str]]:
    """
    Fusionne plusieurs sorties AI : descriptions et mots-clés.
    Applique la normalisation si elle est fournie.
    """
    all_keywords: list[str] = []
    all_descriptions: list[str] = []
    try:
        for item in batch_outputs:
            if isinstance(item, dict):
                if "keywords" in item and isinstance(item["keywords"], list):
                    all_keywords.extend(item["keywords"])
                if "description" in item and isinstance(item["description"], str):
                    desc = item["description"].strip()
                    if desc:
                        all_descriptions.append(desc)

        # 🧹 Nettoyage, déduplication
        raw_keywords = sorted({kw.strip().lower() for kw in all_keywords if isinstance(kw, str) and kw.strip()})

        # ✨ Application de la normalisation (si fourni)
        if normalizer:
            normalized_keywords = normalizer.normalize_keywords(raw_keywords)
        else:
            normalized_keywords = raw_keywords

        # 🧱 Limites de sécurité
        MAX_KEYWORDS = 50
        MAX_KEYWORD_LEN = 50
        filtered_keywords = [kw for kw in normalized_keywords if len(kw) <= MAX_KEYWORD_LEN][:MAX_KEYWORDS]

        # 🧩 Description fusionnée
        merged_description = " ".join(all_descriptions).strip()

        return merged_description, filtered_keywords
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors du merge des mots clés.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"batch_outputs": batch_outputs}),
        ) from exc


def delete_frames(path: Path = Path(TMP_FRAMES_DIR_SC)) -> None:
    """
    delete_frames _summary_

    _extended_summary_

    Args:
        path (Path, optional): _description_. Defaults to Path(TMP_FRAMES_DIR_SC).
    """
    for file in Path(path).glob("*.jpg"):
        try:
            file.unlink()
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur inattendue lors de la suppression des frames.",
                code=ErrCode.UNEXPECTED,
                ctx=get_step_ctx({"path": path, "name": file.name}),
            ) from exc
