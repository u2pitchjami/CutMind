"""
🔎 smartcut.analyze.analyze_confidence
-------------------------------------
Calcule un score de confiance entre la description IA et les mots-clés d’un segment.
Utilise Sentence Transformers (all-MiniLM-L6-v2).
"""

from __future__ import annotations

from sentence_transformers import SentenceTransformer, util

from shared.models.config_manager import CONFIG
from shared.utils.logger import get_logger

logger = get_logger(__name__)

MODEL_CONFIDENCE: str = CONFIG.smartcut["analyse_confidence"]["model_confidence"]

# Charger le modèle globalement (évite de le recharger à chaque segment)
try:
    MODEL = SentenceTransformer(MODEL_CONFIDENCE)
    logger.info(f"✅ Modèle d'embedding chargé : {MODEL_CONFIDENCE}")
except Exception as e:
    logger.error(f"❌ Erreur lors du chargement du modèle de similarité : {e}")
    MODEL = None


def compute_confidence(description: str, keywords: list[str]) -> float:
    """
    Calcule un score de confiance entre la description et les mots-clés associés.

    Retourne un score entre 0.0 et 1.0 basé sur la similarité cosinus.
    Si le modèle n’est pas dispo ou les champs vides → renvoie 0.0.
    """
    try:
        if not description or not keywords:
            return 0.0

        text_keywords = ", ".join(keywords)
        desc_emb = MODEL.encode(description, convert_to_tensor=True)
        key_emb = MODEL.encode(text_keywords, convert_to_tensor=True)
        score: float = util.cos_sim(desc_emb, key_emb).item()

        # Clamp dans [0, 1]
        score = max(0.0, min(1.0, float(score)))
        logger.debug(f"🔹 Score de confiance : {score:.3f} (desc='{description[:30]}...')")

        return round(score, 3)

    except Exception as e:
        logger.warning(f"⚠️ Erreur calcul confiance : {e}")
        return 0.0


# Exemple d’usage intégré
if __name__ == "__main__":
    desc = "Un chat dort sur une chaise en bois."
    keywords = ["chat", "sieste", "chaise", "intérieur"]
    print(compute_confidence(desc, keywords))
