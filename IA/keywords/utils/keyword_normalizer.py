"""
keyword_normalizer.py — version avec mode configurable
------------------------------------------------------
Normalisation des mots-clés avec mapping manuel + embeddings + modes de filtrage.
"""

import json
from pathlib import Path

from sentence_transformers import SentenceTransformer, util

from shared.utils.config import KW_CACHE_FILE_SC, KW_FORBIDDEN_FILE_SC, KW_MAPPING_FILE_SC
from shared.utils.logger import LoggerProtocol, ensure_logger


class KeywordNormalizer:
    """
    Normalise les mots-clés via un mapping manuel, embeddings et fichiers JSON.
    """

    def __init__(
        self,
        model_name: str,
        threshold: float,
        mode: str,  # "full", "strict" ou "mixed"
        mapping_path: Path = KW_MAPPING_FILE_SC,
        forbidden_path: Path = KW_FORBIDDEN_FILE_SC,
        logger: LoggerProtocol | None = None,
    ) -> None:
        self.logger = ensure_logger(logger, __name__)
        self.model = SentenceTransformer(model_name)
        self.threshold = threshold
        self.mapping = self._load_mapping(mapping_path)
        self.forbidden = self._load_forbidden(forbidden_path)
        self.cache = self._load_cache()
        self.mode = mode
        # Tri et sauvegarde automatique des fichiers au démarrage
        self._save_mapping()
        self._save_forbidden()

        if self.mode not in {"full", "strict", "mixed"}:
            raise ValueError("Mode invalide : choisissez 'full', 'strict' ou 'mixed'.")

    # -------------------- Gestion fichiers -------------------- #

    def _load_mapping(self, path: Path) -> dict[str, str]:
        """
        Charge le mapping depuis mapping.json, ou renvoie un dict vide si absent.
        """
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)

                if not isinstance(data, dict):
                    self.logger.warning("⚠️ Le fichier mapping.json n'est pas un dictionnaire valide.")
                    return {}

                sorted_data = dict(sorted(data.items()))
                self.logger.debug("✅ Mapping chargé depuis %s (%d entrées).", path, len(sorted_data))
                return {str(k).lower(): str(v).lower() for k, v in sorted_data.items()}

            except json.JSONDecodeError:
                self.logger.error("❌ Erreur de parsing JSON pour %s — fichier ignoré.", path)
                return {}
            except Exception as exc:
                self.logger.error("💥 Erreur inattendue lors du chargement du mapping : %s", exc)
                return {}
        else:
            self.logger.debug("ℹ️ Aucun mapping.json trouvé — aucun mapping appliqué.")
            return {}

    def _save_mapping(self) -> None:
        """
        Sauvegarde le mapping trié alphabétiquement dans mapping.json.
        """
        try:
            sorted_mapping = dict(sorted(self.mapping.items()))
            with open(KW_MAPPING_FILE_SC, "w", encoding="utf-8") as f:
                json.dump(sorted_mapping, f, indent=2, ensure_ascii=False)
            self.logger.debug("Mapping sauvegardé (%d entrées, trié alphabétiquement).", len(sorted_mapping))
        except Exception as e:
            self.logger.error("Erreur lors de la sauvegarde du mapping : %s", e)

    def _load_forbidden(self, path: Path) -> set[str]:
        """
        Charge la liste de mots interdits depuis forbidden.json et la trie alphabétiquement.
        """
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                sorted_data = sorted({str(d).lower() for d in data})
                self.logger.debug(
                    "Liste de mots interdits chargée depuis %s (%d entrées triées).", path, len(sorted_data)
                )
                return set(sorted_data)
            except json.JSONDecodeError:
                self.logger.warning("Erreur de parsing JSON pour %s — pas de filtre appliqué.", path)
        else:
            self.logger.debug("Aucun forbidden.json trouvé — pas de filtre appliqué.")
        return set()

    def _save_forbidden(self) -> None:
        """
        Sauvegarde la liste de mots interdits triée alphabétiquement dans forbidden.json.
        """
        try:
            sorted_forbidden = sorted(set(self.forbidden))
            with open(KW_FORBIDDEN_FILE_SC, "w", encoding="utf-8") as f:
                json.dump(sorted_forbidden, f, indent=2, ensure_ascii=False)
            self.logger.debug("Liste de mots interdits sauvegardée (%d entrées triées).", len(sorted_forbidden))
        except Exception as e:
            self.logger.error("Erreur lors de la sauvegarde de la liste interdite : %s", e)

    def _load_cache(self) -> dict[str, str]:
        """
        Charge le cache depuis keyword_cache.json et le trie alphabétiquement.
        """
        if KW_CACHE_FILE_SC.exists():
            try:
                with open(KW_CACHE_FILE_SC, encoding="utf-8") as f:
                    cache = json.load(f)
                sorted_cache = dict(sorted(cache.items()))
                self.logger.debug("Cache chargé depuis %s (%d entrées triées).", KW_CACHE_FILE_SC, len(sorted_cache))
                return sorted_cache
            except json.JSONDecodeError:
                self.logger.warning("Cache corrompu, recréation.")
        else:
            self.logger.debug("Aucun cache existant trouvé — initialisation d’un cache vide.")
        return {}

    def _save_cache(self) -> None:
        """
        Sauvegarde le cache trié alphabétiquement dans keyword_cache.json.
        """
        try:
            sorted_cache = dict(sorted(self.cache.items()))
            with open(KW_CACHE_FILE_SC, "w", encoding="utf-8") as f:
                json.dump(sorted_cache, f, indent=2, ensure_ascii=False)
            self.logger.debug("Cache sauvegardé (%d entrées, trié alphabétiquement).", len(sorted_cache))
        except Exception as e:
            self.logger.error("Erreur lors de la sauvegarde du cache : %s", e)

    # -------------------- Normalisation -------------------- #

    def _normalize_with_embeddings(self, word: str, candidates: list[str]) -> str:
        """
        Compare un mot avec les candidats via embeddings et retourne le plus proche.
        """
        word_emb = self.model.encode(word, convert_to_tensor=True)
        if len(word_emb.shape) > 1 and word_emb.shape[0] > 1:
            self.logger.debug(f"⚙️ Moyenne des {word_emb.shape[0]} tokens pour '{word}'.")
            word_emb = word_emb.mean(dim=0, keepdim=True)
        self.logger.debug("Nombre de candidats reçus : %d", len(candidates))
        self.logger.debug("Exemples de candidats : %s", candidates[:10])
        cand_emb = self.model.encode(candidates, convert_to_tensor=True)

        # 🧠 --- LOGS DE DIAGNOSTIC ---
        self.logger.debug(
            "🔍 _normalize_with_embeddings — word='%s' | word_emb.shape=%s | cand_emb.shape=%s",
            word,
            tuple(word_emb.shape),
            tuple(cand_emb.shape),
        )
        # ⚙️ --- PATCH : moyenne des tokens si le mot d'entrée produit plusieurs embeddings ---
        if len(word_emb.shape) > 1 and word_emb.shape[0] > 1:
            self.logger.debug(
                "⚙️ Moyenne des %d tokens du mot '%s' pour un embedding global.",
                word_emb.shape[0],
                word,
            )
            word_emb = word_emb.mean(dim=0, keepdim=True)

        scores = util.cos_sim(word_emb, cand_emb)[0]

        # Log les stats du tensor
        self.logger.debug(
            "Scores tensor shape=%s | device=%s | valeurs=%s",
            tuple(scores.shape),
            scores.device,
            scores[:10],  # affiche les 10 premiers max
        )

        best_idx = int(scores.argmax())
        best_score = float(scores[best_idx])
        self.logger.debug(
            "✅ Best match index=%d | best_score=%.4f | candidate='%s'",
            best_idx,
            best_score,
            candidates[best_idx] if candidates else "N/A",
        )

        return candidates[best_idx] if best_score >= self.threshold else word

    def normalize(self, word: str) -> str:
        word = word.lower().strip()

        if word in self.cache:
            return self.cache[word]

        if word in self.mapping:
            norm = self.mapping[word]
            self.cache[word] = norm
            return norm

        candidates = list(set(self.mapping.values()))
        norm = self._normalize_with_embeddings(word, candidates)
        self.cache[word] = norm
        self._save_cache()

        if norm != word:
            self.logger.debug("→ '%s' reconnu comme '%s' (similarité sémantique)", word, norm)
        return norm

    # -------------------- Mode de traitement -------------------- #

    def normalize_keywords(self, keywords: str | list[str]) -> list[str]:
        """
        Normalise une liste ou une chaîne de mots-clés.
        """
        # 🔹 Accepte str ou list
        if isinstance(keywords, str):
            mots = [m.strip() for m in keywords.split(",") if m.strip()]
        elif isinstance(keywords, list):
            mots = [m.strip() for m in keywords if isinstance(m, str) and m.strip()]
        else:
            mots = []

        # 🔹 Normalisation individuelle
        normalises = [self.normalize(m) for m in mots]
        # 🔹 Gestion du mode
        if self.mode == "strict":
            normalises = [m for m in normalises if m in self.mapping.values()]
        elif self.mode == "mixed":
            normalises = sorted(set(normalises), key=lambda x: x not in self.mapping.values())
        else:
            normalises = sorted(set(normalises))

        # 🔹 Filtrage final
        normalises = [m for m in normalises if m.lower() not in self.forbidden]

        return normalises
