"""Client commun aux consommateurs d’embeddings Ollama."""

from __future__ import annotations

import math

import requests

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.settings import AnalyseConfidenceSettings, KeywordNormalizerSettings


class OllamaEmbeddingClient:
    def __init__(self, settings: AnalyseConfidenceSettings | KeywordNormalizerSettings):
        self.settings = settings

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        settings = self.settings
        context = {"backend": "ollama", "model": settings.ollama_model}
        try:
            with requests.post(
                f"{settings.ollama_base_url}/api/embed",
                json={
                    "model": settings.ollama_model,
                    "input": texts,
                    "truncate": False,
                    "keep_alive": settings.ollama_keep_alive,
                },
                timeout=(10, settings.ollama_timeout),
            ) as response:
                try:
                    response.raise_for_status()
                except requests.HTTPError as exc:
                    detail = ""
                    try:
                        data = response.json()
                        if isinstance(data, dict) and isinstance(data.get("error"), str):
                            detail = data["error"][:1000]
                    except ValueError:
                        pass
                    raise ValueError(f"Ollama HTTP {response.status_code} : {detail or 'erreur HTTP'}") from exc
                data = response.json()

            if not isinstance(data, dict):
                raise ValueError("La réponse Ollama n'est pas un objet JSON.")
            if data.get("error"):
                raise ValueError(f"Erreur Ollama : {data['error']}")
            embeddings = data.get("embeddings")
            if not isinstance(embeddings, list) or len(embeddings) != len(texts):
                raise ValueError("Nombre d'embeddings incorrect.")
            for vector in embeddings:
                if not isinstance(vector, list) or not vector:
                    raise ValueError("Embedding vide ou invalide.")
                if any(type(value) not in (int, float) or not math.isfinite(value) for value in vector):
                    raise ValueError("Embedding non numérique ou non fini.")
            dimensions = len(embeddings[0])
            for vector in embeddings:
                if len(vector) != dimensions:
                    raise ValueError("Dimensions des embeddings différentes.")
                norm = math.hypot(*vector)
                if not norm or not math.isfinite(norm):
                    raise ValueError("Norme d'embedding nulle ou invalide.")
            return embeddings
        except Exception as exc:
            raise CutMindError(
                f"Erreur pendant le calcul des embeddings Ollama : {exc}",
                code=ErrCode.IAERROR,
                ctx=get_step_ctx(context),
            ) from exc


def cosine_similarity(left: list[float], right: list[float]) -> float:
    left_norm, right_norm = math.hypot(*left), math.hypot(*right)
    return math.fsum(a / left_norm * (b / right_norm) for a, b in zip(left, right, strict=True))
