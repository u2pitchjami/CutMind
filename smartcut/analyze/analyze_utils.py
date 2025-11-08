""" """

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re

from shared.models.config_manager import CONFIG
from shared.utils.config import TMP_FRAMES_DIR_SC
from shared.utils.logger import get_logger
from smartcut.models_sc.ai_result import AIResult
from smartcut.models_sc.smartcut_model import SmartCutSession
from smartcut.norm_keywords.keyword_normalizer import KeywordNormalizer

logger = get_logger(__name__)

QBIT = CONFIG.smartcut["analyse_segment"]["4bit"]
BFLOAT16 = CONFIG.smartcut["analyse_segment"]["bfloat16"]
FLOAT16 = CONFIG.smartcut["analyse_segment"]["float16"]
FLOAT32 = CONFIG.smartcut["analyse_segment"]["float32"]
DEFAULT = CONFIG.smartcut["analyse_segment"]["default"]


def extract_keywords_from_filename(filename: str | Path) -> list[str]:
    """
    Extrait automatiquement des mots-clés à partir du nom de fichier.
    Exemple :
        'voyage_-_New_York_-_chouette.mp4' → ['voyage', 'New York', 'chouette']
    """
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
    logger.info(
        f"🧮 VRAM libre : {free_vram_gb:.2f} Go / {total_vram_gb / 1e9:.2f} Go total | "
        f"Précision : {model_precision} | Coût/item : {est_mem_per_image:.2f} Go | "
        f"Marge : {safety_margin_gb:.2f} Go → Batch recommandé = {batch_size}"
    )

    return batch_size


def compute_num_frames(segment_duration: float, base_rate: int = 5) -> int:
    """
    Compute number of frames to extract dynamically.

    - base_rate: number of frames per minute of video.
    - Minimum 3 frames per segment.
    """
    frames = max(3, int(base_rate * (segment_duration / 60)))
    logger.debug(f"({base_rate} * ({segment_duration} / 60) : {frames}")
    return frames


def merge_keywords_across_batches(batch_outputs: list[AIResult]) -> tuple[str, list[str]]:
    """
    Fusionne plusieurs réponses contenant des descriptions et des mots-clés.

    - Gère les formats :
        - JSON : {"Description": "...", "Keywords": ["mot1", "mot2", ...]}
        - Texte brut : "mot1, mot2, mot3"
    - Supprime les doublons et trie les mots.
    - Concatène les descriptions de manière lisible.

    Retourne :
        (description_finale: str, keywords_uniques: list[str])
    """

    all_keywords: list[str] = []
    all_descriptions = []

    for item in batch_outputs:
        # Si c'est déjà un dictionnaire Python
        if isinstance(item, dict):
            if "keywords" in item:
                all_keywords.extend(item["keywords"])
            if "description" in item:
                desc = item["description"].strip()
                if desc:
                    all_descriptions.append(desc)

        # Si c'est une chaîne
        elif isinstance(item, str):
            try:
                # Tente de parser comme JSON
                parsed = json.loads(item)
                if "Keywords" in parsed:
                    all_keywords.extend(parsed["Keywords"])
                if "Description" in parsed:
                    desc = parsed["Description"].strip()
                    if desc:
                        all_descriptions.append(desc)
            except json.JSONDecodeError:
                # Sinon, traite comme une simple liste de mots séparés par des virgules
                for kw in item.split(","):
                    clean_kw = kw.strip().lower()
                    if clean_kw:
                        all_keywords.append(clean_kw)

    # Nettoyage et tri
    unique_keywords = sorted({kw.lower() for kw in all_keywords})
    merged_description = " ".join(all_descriptions).strip()

    return merged_description, unique_keywords


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
