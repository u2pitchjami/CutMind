"""Normalisation Ollama sans configuration de production ni modèle local."""

import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from shared.models.exceptions import CutMindError
from shared.utils.settings import KeywordNormalizerSettings
from tests.test_keywords_backends import load_isolated_module


class NormalizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.enterContext(patch.dict(os.environ, {}, clear=True))
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.mapping = self.root / "mapping.json"
        self.mapping.write_text('{"arbres": "forêt", "eau": "lac"}')
        self.forbidden = self.root / "forbidden.json"
        self.forbidden.write_text('["lac"]')
        self.cache = self.root / "cache.json"
        self.cache.write_text('{"bois": "ancien"}')
        self.settings = KeywordNormalizerSettings("local", "full", 0.8, backend="ollama", ollama_model="embed:test")
        self.module = load_isolated_module(
            "IA/keywords/utils/keyword_normalizer.py",
            {
                "shared.utils.config": SimpleNamespace(
                    KW_CACHE_FILE_SC=self.cache,
                    KW_MAPPING_FILE_SC=self.mapping,
                    KW_FORBIDDEN_FILE_SC=self.forbidden,
                ),
                "shared.utils.logger": SimpleNamespace(LoggerProtocol=object, ensure_logger=lambda *_: MagicMock()),
            },
        )
        self.module.get_settings = lambda: SimpleNamespace(keyword_normalizer=self.settings)
        self.post = self.enterContext(patch("IA.ollama_embeddings.requests.post"))
        self.response = self.post.return_value.__enter__.return_value
        # Candidats triés : forêt, lac.
        self.response.json.return_value = {"embeddings": [[1, 0], [1, 0], [0, 1]]}
        self.normalizer = self.module.KeywordNormalizer("local", 0.8, "full")

    def test_ollama_matching_and_cache(self) -> None:
        self.assertIsNone(self.normalizer.model)
        self.assertEqual(self.normalizer.normalize(" Bois "), "forêt")
        self.assertEqual(self.post.call_args.kwargs["json"]["input"], ["bois", "forêt", "lac"])
        self.assertEqual(self.normalizer.normalize("bois"), "forêt")
        self.post.assert_called_once()
        self.assertEqual(self.cache.read_text(), '{"bois": "ancien"}')

    def test_manual_mapping_and_filter(self) -> None:
        self.assertEqual(self.normalizer.normalize_keywords(["arbres", "eau"]), ["forêt"])
        self.post.assert_not_called()

    def test_threshold_and_modes(self) -> None:
        self.response.json.return_value = {"embeddings": [[1, 0], [0, 1], [0, 1]]}
        self.assertEqual(self.normalizer.normalize_keywords(["inconnu"]), ["inconnu"])
        self.normalizer.mode = "strict"
        self.assertEqual(self.normalizer.normalize_keywords(["inconnu", "arbres"]), ["forêt"])
        self.normalizer.mode = "mixed"
        self.assertEqual(self.normalizer.normalize_keywords(["inconnu", "arbres"]), ["forêt", "inconnu"])

    def test_no_candidates_or_error(self) -> None:
        self.assertEqual(self.normalizer._normalize_with_embeddings("mot", []), "mot")
        self.post.assert_not_called()
        self.response.json.return_value = {"error": "missing model"}
        with self.assertRaises(CutMindError):
            self.normalizer.normalize("bois")
        self.assertNotIn("bois", self.normalizer.cache)

    def test_settings(self) -> None:
        self.assertEqual(KeywordNormalizerSettings("local", "full", 0.8).backend, "transformers")
        with patch.dict(
            os.environ,
            {
                "KEYWORD_NORMALIZER_BACKEND": "ollama",
                "KEYWORD_NORMALIZER_OLLAMA_MODEL": "env:model",
                "OLLAMA_BASE_URL": "http://server:11434/",
            },
        ):
            settings = KeywordNormalizerSettings("local", "full", 0.8)
            self.assertEqual(settings.ollama_model, "env:model")
            self.assertEqual(settings.ollama_base_url, "http://server:11434")
        with self.assertRaises(ValueError):
            KeywordNormalizerSettings("local", "full", 0.8, backend="ollama")

    def test_transformers_route(self) -> None:
        self.settings.backend = "transformers"
        model = MagicMock()
        with patch.dict("sys.modules", {"sentence_transformers": SimpleNamespace(SentenceTransformer=model)}):
            normalizer = self.module.KeywordNormalizer("local", 0.8, "full")
        model.assert_called_once_with("local")
        self.assertIsNone(normalizer.embedding_client)
        self.assertEqual(normalizer.normalize("bois"), "ancien")
        self.post.assert_not_called()
