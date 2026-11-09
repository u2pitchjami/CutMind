"""Tests sans serveur Ollama, GPU ni configuration de production."""

from __future__ import annotations

import base64
from dataclasses import MISSING, fields
import importlib.util
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import MagicMock, patch

from PIL import Image
import requests

from IA.keywords.utils.ai_result import AIOutputType
from shared.models.exceptions import CutMindError, ErrCode
from shared.utils.settings import GenerateKeywordsSettings

ROOT = Path(__file__).resolve().parents[1]


def load_isolated_module(path: str, stubs: dict[str, Any]) -> Any:
    """Isoler les imports qui chargent normalement le .env et les modèles."""
    spec = importlib.util.spec_from_file_location("backend_under_test", ROOT / path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    with patch.dict("sys.modules", stubs):
        spec.loader.exec_module(module)
    return module


def make_settings(**overrides: Any) -> GenerateKeywordsSettings:
    # Les paramètres HF ne sont pas utilisés par les tests Ollama.
    values: dict[str, Any] = {
        field.name: "unused" for field in fields(GenerateKeywordsSettings) if field.default is MISSING
    }
    values.update(
        sizeh=32, sizel=24, max_new_tokens=128, temperature=0.3, top_p=0.9, repetition_penalty=1.1, do_sample=False
    )
    values.update(overrides)
    return GenerateKeywordsSettings(**values)


class SettingsTests(unittest.TestCase):
    def test_default_and_yaml(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(make_settings().backend, "transformers")
            settings = make_settings(backend="ollama", ollama_model="vision:test")
            self.assertEqual(settings.ollama_model, "vision:test")

    def test_env_overrides_yaml(self) -> None:
        env = {
            "KEYWORDS_BACKEND": "ollama",
            "OLLAMA_MODEL": "vision:env",
            "OLLAMA_BASE_URL": "http://ollama:11434/",
            "OLLAMA_BATCH_SIZE": "3",
            "OLLAMA_NUM_CTX": "32768",
            "OLLAMA_THINK": "true",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = make_settings(ollama_model="vision:yaml")
        self.assertEqual(settings.backend, "ollama")
        self.assertEqual(settings.ollama_model, "vision:env")
        self.assertEqual(settings.ollama_base_url, "http://ollama:11434")
        self.assertEqual(settings.ollama_batch_size, 3)
        self.assertEqual(settings.ollama_num_ctx, 32768)
        self.assertTrue(settings.ollama_think)

    def test_invalid_configuration(self) -> None:
        cases: list[dict[str, Any]] = [
            {"backend": "unknown"},
            {"backend": "ollama", "ollama_model": ""},
            {"ollama_base_url": "file:///tmp/ollama"},
            {"ollama_timeout": 0},
            {"ollama_timeout": float("nan")},
            {"ollama_batch_size": 0},
            {"ollama_num_ctx": 0},
        ]
        for values in cases:
            with self.subTest(values=values), patch.dict(os.environ, {}, clear=True):
                config: dict[str, Any] = {"backend": "ollama", "ollama_model": "vision:test"}
                config.update(values)
                with self.assertRaises(ValueError):
                    make_settings(**config)


class OllamaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.frame_dir = Path(self.temp.name)
        for name, color in [("segment_02.jpg", "blue"), ("segment_01.jpg", "red"), ("other_01.jpg", "green")]:
            Image.new("RGB", (64, 48), color).save(self.frame_dir / name)
        with patch.dict(os.environ, {}, clear=True):
            self.settings = make_settings(backend="ollama", ollama_model="vision:test")
        self.logger = MagicMock()
        stubs = {
            "shared.utils.config": SimpleNamespace(
                PROMPTS={
                    "keywords": "analyse",
                    "system_keywords": "système",
                    "ratings": "notes",
                    "system_ratings": "évaluation",
                }
            ),
            "shared.utils.logger": SimpleNamespace(LoggerProtocol=Any, ensure_logger=lambda *_: self.logger),
        }
        self.client = load_isolated_module("IA/keywords/analyze/ollama_keywords.py", stubs)
        self.client.get_settings = lambda: SimpleNamespace(generate_keywords=self.settings)
        self.post = self.enterContext(patch.object(self.client.requests, "post"))
        self.response = self.post.return_value.__enter__.return_value
        self.analysis = {"description": " Une scène ", "category": "nature", "keywords": ["lac"]}
        self.set_response(self.analysis)

    def set_response(self, content: Any) -> None:
        self.response.json.return_value = {"done": True, "message": {"content": json.dumps(content)}}

    def generate(self, output_type: AIOutputType = AIOutputType.SCENE_ANALYSIS, **kwargs: Any) -> Any:
        return self.client.generate_keywords_with_ollama(self.frame_dir, "segment", 1, output_type, **kwargs)

    def test_images_prompts_and_result(self) -> None:
        result = self.generate()
        self.assertEqual(result["description"], "Une scène")
        args, kwargs = self.post.call_args
        self.assertEqual(args[0], "http://localhost:11434/api/chat")
        self.assertEqual(kwargs["timeout"], (10, 180))
        payload = kwargs["json"]
        self.assertFalse(payload["stream"])
        self.assertFalse(payload["think"])
        self.assertEqual(payload["messages"][0]["content"], "système")
        self.assertEqual(payload["messages"][1]["content"], "analyse")
        images = payload["messages"][1]["images"]
        self.assertEqual(len(images), 1)
        with Image.open(BytesIO(base64.b64decode(images[0]))) as image:
            self.assertEqual(image.size, (32, 24))
            self.assertGreater(image.getpixel((0, 0))[0], 200)  # frame 01, rouge
        self.assertEqual(payload["options"]["temperature"], 0)
        self.assertEqual(payload["options"]["num_ctx"], 16384)
        self.assertEqual(payload["format"]["required"], ["description", "category", "keywords"])

    def test_ratings_and_custom_prompts(self) -> None:
        self.set_response({"quality_rating": 4, "interest_rating": 8})
        result = self.generate(AIOutputType.SCENE_RATING, prompt_name="ratings", system_prompt="system_ratings")
        self.assertEqual(result, {"quality_rating": 4.0, "interest_rating": 8.0})
        payload = self.post.call_args.kwargs["json"]
        self.assertEqual(payload["messages"][1]["content"], "notes")
        self.assertEqual(payload["format"]["required"], ["quality_rating", "interest_rating"])

    def test_bad_responses(self) -> None:
        cases = [
            [],
            {"error": "model unavailable"},
            {"done": False},
            {"done": True, "done_reason": "length", "message": {"content": "{}"}},
            {"done": True, "message": {"content": ""}},
            {"done": True, "message": {"content": "invalid json"}},
            {"done": True, "message": {"content": "{}"}},
        ]
        for response in cases:
            with self.subTest(response=response):
                self.response.json.return_value = response
                with self.assertRaises(CutMindError) as raised:
                    self.generate()
                self.assertEqual(raised.exception.code, ErrCode.IAERROR)
                self.assertEqual(raised.exception.ctx["backend"], "ollama")

    def test_network_errors(self) -> None:
        for error in [requests.Timeout("timeout"), requests.ConnectionError("connection"), requests.HTTPError("404")]:
            with self.subTest(error=error):
                self.post.side_effect = error
                with self.assertRaises(CutMindError) as raised:
                    self.generate()
                self.assertIs(raised.exception.__cause__, error)

    def test_truncated_thinking_response_has_diagnostics(self) -> None:
        self.response.json.return_value = {
            "done": True,
            "done_reason": "length",
            "eval_count": 128,
            "message": {"content": "", "thinking": "reasoning"},
        }
        with self.assertRaises(CutMindError) as raised:
            self.generate()
        self.assertIn("raison=length", str(raised.exception))
        self.assertIn("tokens générés=128", str(raised.exception))
        self.assertIn("raisonnement présent=True", str(raised.exception))

    def test_thinking_can_be_enabled(self) -> None:
        self.settings.ollama_think = True
        self.generate()
        self.assertTrue(self.post.call_args.kwargs["json"]["think"])

    def test_http_error_preserves_server_reason(self) -> None:
        self.response.status_code = 404
        self.response.raise_for_status.side_effect = requests.HTTPError("404 Not Found")
        self.response.json.return_value = {"error": "model 'vision:test' not found"}
        with self.assertRaises(CutMindError) as raised:
            self.generate()
        self.assertIn("model 'vision:test' not found", str(raised.exception))
        self.assertEqual(raised.exception.ctx["status"], 404)

    def test_missing_frames_never_calls_server(self) -> None:
        with self.assertRaises(CutMindError) as raised:
            self.client.generate_keywords_with_ollama(self.frame_dir, "missing", 2, AIOutputType.SCENE_ANALYSIS)
        self.assertEqual(raised.exception.code, ErrCode.NOFILE)
        self.post.assert_not_called()

    def test_router_selects_backend_without_fallback(self) -> None:
        hf = MagicMock()
        ollama = MagicMock()
        stubs = {
            "transformers": SimpleNamespace(PreTrainedModel=Any, ProcessorMixin=Any),
            "shared.utils.logger": SimpleNamespace(LoggerProtocol=Any, ensure_logger=lambda *_: self.logger),
            "IA.keywords.analyze.generate_keywords": SimpleNamespace(generate_keywords_from_frames=hf),
            "IA.keywords.analyze.ollama_keywords": SimpleNamespace(generate_keywords_with_ollama=ollama),
        }
        router = load_isolated_module("IA/keywords/main_gen_keywords.py", stubs)
        router.get_settings = lambda: SimpleNamespace(generate_keywords=self.settings)
        with patch.dict("sys.modules", stubs):
            args = ("segment", self.frame_dir, None, None, 1, AIOutputType.SCENE_ANALYSIS)
            router.generate_keywords_for_segment(*args)
            ollama.assert_called_once()
            hf.assert_not_called()
            ollama.side_effect = CutMindError("Ollama KO", code=ErrCode.IAERROR)
            with self.assertRaises(CutMindError):
                router.generate_keywords_for_segment(*args)
            hf.assert_not_called()
            self.settings.backend = "transformers"
            router.generate_keywords_for_segment(
                "segment", self.frame_dir, MagicMock(), MagicMock(), 1, AIOutputType.SCENE_ANALYSIS
            )
            hf.assert_called_once()


if __name__ == "__main__":
    unittest.main()
