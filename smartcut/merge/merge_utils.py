""" """

from __future__ import annotations

import re

from shared.utils.logger import get_logger

logger = get_logger(__name__)


def clean(text: str) -> list[str]:
    """
    Nettoie une chaîne (séparateurs, minuscules, découpage en mots).
    """
    if not isinstance(text, str):
        text = str(text)
    return re.sub(r"[^\w\s]", " ", text.lower()).split()


def keyword_similarity(a: list[str], b: list[str]) -> float:
    """
    Score de similarité basique entre deux listes de mots-clés (Jaccard).
    """
    logger.debug(f"a : {type(a)} : {a[:50]}")
    logger.debug(f"b : {type(b)} : {b[:50]}")
    words_a = [w for kw in a for w in clean(kw)]
    words_b = [w for kw in b for w in clean(kw)]
    logger.debug(f"words_a : {type(words_a)} : {words_a[:50]}")
    logger.debug(f"words_b : {type(words_b)} : {words_b[:50]}")
    set_a = set(words_a)
    set_b = set(words_b)

    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    score = inter / union if union > 0 else 0.0

    logger.debug("Similarity between %s and %s = %.2f", set_a, set_b, score)
    return score


if __name__ == "__main__":
    keyword_similarity(a=["truc, bidule"], b=["bidule, chouette"])
