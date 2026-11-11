"""Similarité description/mots-clés via les embeddings Ollama."""

from IA.ollama_embeddings import OllamaEmbeddingClient, cosine_similarity
from shared.utils.settings import AnalyseConfidenceSettings


class OllamaConfidenceExecutor:
    def __init__(self, settings: AnalyseConfidenceSettings):
        self.client = OllamaEmbeddingClient(settings)

    def compute(self, description: str, keywords: list[str]) -> float:
        if not description or not keywords:
            return 0.0
        left, right = self.client.embed([description, ", ".join(keywords)])
        return max(0.0, min(1.0, round(cosine_similarity(left, right), 3)))
