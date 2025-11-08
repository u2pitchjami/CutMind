"""
🔎 smartcut.analyze.analyze_confidence
-------------------------------------
Calcule un score de confiance entre la description IA et les mots-clés d’un segment.
Utilise Sentence Transformers (ex: all-MiniLM-L6-v2 ou BAAI/bge-m3).
"""

from __future__ import annotations

from sentence_transformers import SentenceTransformer, util
import torch

from shared.models.config_manager import CONFIG
from shared.utils.logger import get_logger

logger = get_logger(__name__)

MODEL_CONFIDENCE: str = CONFIG.smartcut["analyse_confidence"]["model_confidence"]
DEVICE: str = CONFIG.smartcut["analyse_confidence"]["device"]

# 🔧 Initialisation du modèle global
MODEL = None


def get_confidence_model() -> SentenceTransformer:
    """
    Charge le modèle de similarité en mémoire (lazy-load, CPU par défaut).
    """
    global MODEL, DEVICE
    if MODEL is not None:
        return MODEL

    try:
        # 💡 Vérifie si le GPU est dispo, mais reste CPU par défaut
        if torch.cuda.is_available():
            total_mem = torch.cuda.get_device_properties(0).total_memory
            if total_mem >= 16 * 1024**3:
                DEVICE = "cuda"
                logger.info("⚙️ GPU détecté — modèle sur CUDA (VRAM >= 16 Go)")
            else:
                logger.info("⚙️ GPU limité — modèle forcé sur CPU")
        else:
            logger.info("⚙️ Pas de GPU détecté — modèle forcé sur CPU")

        MODEL = SentenceTransformer(MODEL_CONFIDENCE, device=DEVICE)
        logger.info(f"✅ Modèle de similarité chargé sur {DEVICE.upper()} : {MODEL_CONFIDENCE}")

    except Exception as e:
        logger.error(f"❌ Erreur chargement modèle confiance : {e}")
        MODEL = None

    return MODEL


def compute_confidence(description: str, keywords: list[str]) -> float:
    """
    Calcule un score de confiance entre la description et les mots-clés associés.

    Retourne un score entre 0.0 et 1.0 basé sur la similarité cosinus.
    Si le modèle n’est pas dispo ou les champs vides → renvoie 0.0.
    """
    try:
        if not description or not keywords:
            return 0.0

        model = get_confidence_model()
        if not model:
            logger.warning("⚠️ Aucun modèle disponible pour le calcul de confiance.")
            return 0.0

        text_keywords = ", ".join(keywords)

        # 🔹 Encodage CPU/GPU auto
        desc_emb = model.encode(description, convert_to_tensor=True)
        key_emb = model.encode(text_keywords, convert_to_tensor=True)

        score: float = util.cos_sim(desc_emb, key_emb).item()
        score = max(0.0, min(1.0, float(score)))

        logger.debug(f"🔹 Score de confiance : {score:.3f} (desc='{description[:30]}...')")
        return round(score, 3)

    except Exception as e:
        logger.warning(f"⚠️ Erreur calcul confiance : {e}")
        return 0.0


if __name__ == "__main__":
    desc = "Un chat dort sur une chaise en bois."
    keywords = ["chat", "sieste", "chaise", "intérieur"]
    print(compute_confidence(desc, keywords))
