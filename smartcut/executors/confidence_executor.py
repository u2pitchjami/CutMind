from __future__ import annotations

from sentence_transformers import SentenceTransformer, util
import torch

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx


class ConfidenceExecutor:
    """
    Exécuteur spécialisé : calcule un score de similarité entre description et keywords.
    Ne fait aucun log métier, aucune mise à jour session.
    """

    def __init__(self, model_name: str, force_device: str | None = None):
        self.model_name = model_name
        self.force_device = force_device
        self._model: SentenceTransformer | None = None

    def _load(self) -> SentenceTransformer:
        """Chargement lazy du modèle."""
        if self._model is not None:
            return self._model

        try:
            device = self.force_device
            if device is None:
                if torch.cuda.is_available():
                    total = torch.cuda.get_device_properties(0).total_memory
                    device = "cuda" if total >= 16 * 1024**3 else "cpu"
                else:
                    device = "cpu"

            self._model = SentenceTransformer(self.model_name, device=device)
            return self._model

        except Exception as exc:
            raise CutMindError(
                "Échec du chargement du modèle de confiance",
                code=ErrCode.MODEL,
                ctx=get_step_ctx({"model": self.model_name}),
            ) from exc

    def compute(self, description: str, keywords: list[str]) -> float:
        """
        Pure fonction : renvoie un float ∈ [0,1].
        """
        if not description or not keywords:
            return 0.0

        try:
            model = self._load()
            text_kw = ", ".join(keywords)

            desc_emb = model.encode(description, convert_to_tensor=True)
            kw_emb = model.encode(text_kw, convert_to_tensor=True)

            score = float(util.cos_sim(desc_emb, kw_emb).item())
            return max(0.0, min(1.0, round(score, 3)))

        except Exception as exc:
            raise CutMindError(
                "Erreur technique pendant le calcul de confiance",
                code=ErrCode.IAERROR,
                ctx=get_step_ctx({"description": description[:50], "keywords": keywords[:5]}),
            ) from exc
