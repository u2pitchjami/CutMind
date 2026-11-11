"""Régression : une catégorie absente ne bloque pas les segments suivants."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import MagicMock

from IA.keywords.utils.ai_result import AIOutputType
from IA.keywords.utils.parse_output import normalize_category, parse_json_ai_output
from shared.status_orchestrator.statuses import SegmentStatus
from tests.test_keywords_backends import load_isolated_module


class MissingCategoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stubs = {
            "transformers": SimpleNamespace(PreTrainedModel=object, ProcessorMixin=object),
            "shared.models.db_models": SimpleNamespace(Segment=object, Video=object),
            "shared.utils.logger": SimpleNamespace(
                LoggerProtocol=object, ensure_logger=lambda *_: MagicMock(), get_logger=MagicMock()
            ),
            "shared.utils.config": SimpleNamespace(
                BATCH_FRAMES_DIR_SC=Path("/tmp/unused-frames"),
                **dict.fromkeys(["COLOR_BLUE", "COLOR_GREEN", "COLOR_PURPLE", "COLOR_RED", "COLOR_RESET"], ""),
            ),
        }
        modules = {
            "IA.keywords.analyze.analyze_batches": ["process_batches"],
            "IA.keywords.frames.extract_frames": ["compute_phash_from_frame", "extract_segment_frames"],
            "IA.keywords.prep.prep_analyze": ["cleanup_temp", "open_vid", "release_cap"],
            "IA.keywords.utils.analyze_torch_utils": [
                "estimate_visual_tokens",
                "release_gpu_memory",
                "vram_gpu",
                "ModelManager",
            ],
            "shared.executors.ffmpeg_utils": ["get_duration"],
        }
        for module, names in modules.items():
            self.stubs[module] = SimpleNamespace(**{name: MagicMock() for name in names})
        self.stubs["shared.utils.safe_segments"] = SimpleNamespace(safe_segments=lambda f: f)
        self.pipeline = load_isolated_module("IA/keywords/IA_analyze.py", self.stubs)
        self.pipeline.run_prompt_on_batches = MagicMock()

    def test_parser_sentinels(self) -> None:
        for raw in ["null", '"None"', '" none "', '"null"', '""']:
            result = parse_json_ai_output('{"category": ' + raw + "}", AIOutputType.SCENE_ANALYSIS)
            self.assertIn("category", result)
            self.assertIsNone(result["category"])
        self.assertEqual(normalize_category(" nature "), "nature")

    def test_missing_category_stops_after_first_pass(self) -> None:
        for category in [None, "None", " null ", ""]:
            with self.subTest(category=category):
                self.pipeline.run_prompt_on_batches.reset_mock()
                self.pipeline.run_prompt_on_batches.return_value = [{"category": category}]
                result = self.run_pipeline()
                self.assertIsNone(result.category)
                self.pipeline.run_prompt_on_batches.assert_called_once()
                self.assertEqual(self.pipeline.run_prompt_on_batches.call_args.kwargs["prompt_name"], "keywords")

    def run_pipeline(self, categ: str | None = None) -> Any:
        return self.pipeline.run_ai_pipeline_v25(
            video_name="video",
            start=0,
            end=1,
            frame_paths=["frame.jpg"],
            batch_size=1,
            processor=None,
            model=None,
            categ=categ,
            logger=MagicMock(),
        )

    def test_valid_batches_and_manual_category(self) -> None:
        self.assertEqual(
            self.pipeline.merge_category([{"category": "None"}, {"category": None}, {"category": "nature"}]), "nature"
        )
        self.pipeline.run_prompt_on_batches.side_effect = [
            [{"description": "description", "keywords": ["lac"]}],
            [{"quality_rating": 4, "interest_rating": 8}],
        ]
        self.assertEqual(self.run_pipeline(categ="nature").category, "nature")
        self.assertEqual(
            [call.kwargs["prompt_name"] for call in self.pipeline.run_prompt_on_batches.call_args_list],
            ["nature", "rating"],
        )

    def test_worker_continues_and_second_failure_is_terminal(self) -> None:
        stubs = dict(self.stubs)
        history = MagicMock()
        stubs.update(
            {
                "IA.keywords.IA_analyze": SimpleNamespace(analyze_IA=MagicMock()),
                "check.histo.processing_checks": SimpleNamespace(evaluate_ia_output=lambda _: ("ok", "OK")),
                "check.histo.processing_log": SimpleNamespace(processing_step=MagicMock()),
                "db.repository": SimpleNamespace(CutMindRepository=MagicMock()),
                "IA.keywords.prep.load_model": SimpleNamespace(load_and_batches=MagicMock()),
                "IA.keywords.utils.keyword_normalizer": SimpleNamespace(KeywordNormalizer=MagicMock()),
                "shared.services.gpu_guard": SimpleNamespace(guard_gpu_or_requeue=MagicMock()),
            }
        )
        worker_module = load_isolated_module("IA/main_ia.py", stubs)
        worker_module.processing_step.return_value.__enter__.return_value = history
        worker_module.vram_gpu.return_value = (0, 0)
        settings = MagicMock()
        settings.generate_keywords.backend = "ollama"
        worker_module.get_settings = lambda: settings
        worker = worker_module.IAWorker(SimpleNamespace(name="video"), [])
        worker.log_ai_summary = MagicMock()
        missing = SimpleNamespace(id=1, tags=[], status="pending", filename_predicted="missing")
        missing.add_tag = missing.tags.append
        valid = SimpleNamespace(id=2, tags=[], status="pending", filename_predicted="valid")
        worker.segments = [missing, valid]
        worker_module.analyze_IA.side_effect = [
            ("description", None, [], 0, 0, []),
            ("description complète", "nature", [], 4, 8, []),
        ]
        self.assertEqual(worker.run(), 1)
        self.assertEqual(missing.pipeline_target, SegmentStatus.TO_IA)
        self.assertEqual(missing.tags, ["IA_error"])
        self.assertEqual(missing.status, "pending")
        self.assertEqual(valid.pipeline_target, SegmentStatus.TO_CONFIDENCE)
        worker.repo.update_segment_validation.assert_any_call(missing)
        worker.record_ia_failure(missing)
        self.assertEqual(missing.pipeline_target, SegmentStatus.IA_ERROR)
        self.assertEqual(missing.tags, ["IA_error"])
