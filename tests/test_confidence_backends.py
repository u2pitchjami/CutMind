"""Tests confidence sans serveur Ollama ni modèle local."""

import os
from typing import Any
import unittest
from unittest.mock import patch

import requests

from IA.confidence.ollama_confidence import OllamaConfidenceExecutor
from shared.models.exceptions import CutMindError
from shared.utils.settings import AnalyseConfidenceSettings


class ConfidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.enterContext(patch.dict(os.environ, {}, clear=True))
        self.settings = AnalyseConfidenceSettings("local", "cpu", backend="ollama", ollama_model="embed:test")
        self.executor = OllamaConfidenceExecutor(self.settings)
        self.post = self.enterContext(patch("IA.ollama_embeddings.requests.post"))
        self.response = self.post.return_value.__enter__.return_value

    def test_settings(self) -> None:
        self.assertEqual(AnalyseConfidenceSettings("local", "cpu").backend, "transformers")
        with patch.dict(
            os.environ,
            {
                "CONFIDENCE_BACKEND": "ollama",
                "CONFIDENCE_OLLAMA_MODEL": "env:embed",
                "OLLAMA_BASE_URL": "http://server:11434/",
            },
        ):
            settings = AnalyseConfidenceSettings("local", "cpu")
            self.assertEqual(settings.ollama_model, "env:embed")
            self.assertEqual(settings.ollama_base_url, "http://server:11434")
        overrides: list[dict[str, Any]] = [
            {"backend": "unknown"},
            {"ollama_model": ""},
            {"ollama_base_url": "file:///tmp/model"},
            {"ollama_timeout": 0},
            {"ollama_timeout": float("nan")},
        ]
        for override in overrides:
            with self.subTest(override=override), self.assertRaises(ValueError):
                config: dict[str, Any] = {"backend": "ollama", "ollama_model": "embed:test", **override}
                AnalyseConfidenceSettings("local", "cpu", **config)

    def test_similarity_and_payload(self) -> None:
        self.response.json.return_value = {"embeddings": [[1, 0], [3, 4]]}
        self.assertEqual(self.executor.compute("scène", ["lac", "forêt"]), 0.6)
        args, kwargs = self.post.call_args
        self.assertEqual(args[0], "http://localhost:11434/api/embed")
        self.assertEqual(kwargs["json"]["input"], ["scène", "lac, forêt"])
        self.assertEqual(kwargs["json"]["model"], "embed:test")
        self.assertFalse(kwargs["json"]["truncate"])
        self.assertEqual(kwargs["timeout"], (10, 180))

    def test_bounds(self) -> None:
        for vector, expected in [([1, 0], 1.0), ([-1, 0], 0.0), ([0, 1], 0.0)]:
            self.response.json.return_value = {"embeddings": [[1, 0], vector]}
            self.assertEqual(self.executor.compute("scène", ["lac"]), expected)

    def test_empty_input(self) -> None:
        self.assertEqual(self.executor.compute("", ["lac"]), 0)
        self.assertEqual(self.executor.compute("scène", []), 0)
        self.post.assert_not_called()

    def test_invalid_responses(self) -> None:
        for data in [
            [],
            {"error": "missing model"},
            {},
            *[
                {"embeddings": vectors}
                for vectors in [
                    [],
                    [[1]],
                    [[], []],
                    [[1], [1, 2]],
                    [[0], [1]],
                    [[float("nan")], [1]],
                    [[float("inf")], [1]],
                    [[True], [1]],
                    [["1"], [1]],
                ]
            ],
        ]:
            with self.subTest(data=data):
                self.response.json.return_value = data
                with self.assertRaises(CutMindError):
                    self.executor.compute("scène", ["lac"])

    def test_network_errors(self) -> None:
        for error in [requests.Timeout(), requests.ConnectionError()]:
            self.post.side_effect = error
            with self.assertRaises(CutMindError) as raised:
                self.executor.compute("scène", ["lac"])
            self.assertIs(raised.exception.__cause__, error)

    def test_http_error_has_server_detail(self) -> None:
        self.response.raise_for_status.side_effect = requests.HTTPError()
        self.response.status_code = 404
        self.response.json.return_value = {"error": "embedding model missing"}
        with self.assertRaisesRegex(CutMindError, "embedding model missing"):
            self.executor.compute("scène", ["lac"])


if __name__ == "__main__":
    unittest.main()
