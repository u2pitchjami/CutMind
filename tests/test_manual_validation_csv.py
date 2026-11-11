"""Validation manuelle CSV, sans base de données ni fichiers de production."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import MagicMock, patch

from shared.status_orchestrator.statuses import OrchestratorStatus
from tests.test_keywords_backends import ROOT, load_isolated_module


class ManualValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        stubs = {
            "shared.models.db_models": SimpleNamespace(Segment=object),
            "shared.services.file_mover": SimpleNamespace(FileMover=MagicMock()),
            "shared.utils.logger": SimpleNamespace(LoggerProtocol=object, ensure_logger=lambda *_: MagicMock()),
        }
        utils = load_isolated_module("validation/manual/manual_utils.py", stubs)
        self.history = SimpleNamespace(status=None, message=None)
        self.step = MagicMock()
        self.step.return_value.__enter__.return_value = self.history
        stubs.update(
            {
                "validation.manual.manual_utils": utils,
                "check.histo.processing_log": SimpleNamespace(processing_step=self.step),
                "db.db_connection": SimpleNamespace(db_conn=MagicMock(), get_dict_cursor=MagicMock()),
                "db.repository": SimpleNamespace(CutMindRepository=MagicMock()),
                "shared.utils.config": SimpleNamespace(
                    **dict.fromkeys(
                        ["CSV_ARCHIVE_PATH", "CSV_LOG_PATH", "MANUAL_CSV_PATH", "OUTPUT_DIR_SC", "POST_CUT_DIR_SC"],
                        Path("/tmp/unused-csv"),
                    )
                ),
            }
        )
        for module_name, names in {
            "validation.services.delete_segment": ["perform_segment_delete"],
            "validation.services.merge_perform": ["parse_merge_request", "perform_merge"],
            "validation.services.recut_segment": ["parse_recut_points", "perform_recut"],
            "validation.services.rename_video": ["perform_video_rename"],
        }.items():
            stubs[module_name] = SimpleNamespace(**{name: MagicMock(return_value=None) for name in names})
        spec = importlib.util.spec_from_file_location(
            "csv_validation_under_test", ROOT / "validation/manual/update_from_csv.py"
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        with patch.dict("sys.modules", {**stubs, spec.name: module}):
            spec.loader.exec_module(module)
        self.module = module
        self.repo = MagicMock()
        self.segment = SimpleNamespace(
            id=1,
            uid="seg",
            description="ancienne description",
            keywords=["ancien"],
            category="nature",
            confidence=0.25,
            status=OrchestratorStatus.SEGMENT_CONFIDENCE_DONE,
            pipeline_target="pending_check",
        )
        self.video = SimpleNamespace(id=2, name="video", segments=[self.segment])
        self.repo.get_video_id_from_segment_id.return_value = 2
        self.repo.get_video_with_segments.return_value = self.video
        self.row = {
            "segment_id": "1",
            "video_id": "999",
            "video_name": "autre",
            "description": "description corrigée",
            "keywords": "lac, forêt",
            "category": "nature",
            "confidence": "0.99",
            "status": "confidence_done",
            "pipeline_target": "TO_IA",
            "action": "val",
        }
        self.stats = module.ImportStats()
        self.logs: list[dict[str, str]] = []
        self.logger = MagicMock()

    def process(self) -> tuple[dict[str, Any], dict[str, Any]] | None:
        self.module._process_csv_row(self.row, self.repo, self.stats, self.logs, self.logger)
        if self.repo.update_segment_from_csv.called:
            _, data, diffs = self.repo.update_segment_from_csv.call_args.args
            return data, diffs
        return None

    def test_val_preserves_score_and_validates(self) -> None:
        result = self.process()
        assert result is not None
        data, diffs = result
        self.assertEqual(data["status"], OrchestratorStatus.SEGMENT_VALIDATED)
        self.assertEqual(data["pipeline_target"], OrchestratorStatus.SEGMENT_TO_CHECK)
        self.assertEqual(data["confidence"], 0.25)
        self.assertEqual(data["description"], "description corrigée")
        self.assertEqual(data["keywords"], ["forêt", "lac"])
        self.assertEqual(data["video_id"], 2)
        self.assertNotIn("confidence", diffs)
        self.assertEqual(self.stats.updated, 1)
        self.assertEqual(self.stats.errors, 0)
        self.step.assert_called_once_with(self.video, self.segment, action="Validation finale manuelle via CSV")
        self.assertEqual(self.history.status, "ok")
        self.assertEqual(self.logs[0]["action"], "Validation finale manuelle via CSV")

    def test_val_missing_metadata_rejects_entire_row(self) -> None:
        for field, value in [("category", "None"), ("description", " "), ("keywords", "NULL")]:
            with self.subTest(field=field):
                self.repo.reset_mock()
                original = self.row[field]
                self.row[field] = value
                self.process()
                self.row[field] = original
                self.repo.update_segment_from_csv.assert_not_called()
                self.repo.update_video.assert_not_called()
                self.step.assert_not_called()
        self.assertEqual(self.stats.errors, 3)
        self.assertEqual(self.stats.updated, 0)

    def test_ok_clears_ia_metadata_and_keeps_cut_route(self) -> None:
        self.row["action"] = " OK "
        result = self.process()
        assert result is not None
        data, diffs = result
        self.assertEqual(data["description"], "")
        self.assertEqual(data["keywords"], [])
        self.assertIn("description", diffs)
        self.assertIn("keywords", diffs)
        self.assertEqual(data["category"], "nature")
        self.assertEqual(data["confidence"], 0.99)
        self.assertEqual(data["status"], OrchestratorStatus.SEGMENT_CUT_VALIDATED)
        self.assertEqual(data["pipeline_target"], OrchestratorStatus.SEGMENT_TO_ENHANCE)
        self.assertEqual(self.stats.updated, 1)
        self.step.assert_not_called()

    def test_ok_without_category_keeps_existing_confidence_behavior(self) -> None:
        self.row.update(action="ok", category="", confidence="0.25")
        result = self.process()
        assert result is not None
        data, _ = result
        self.assertEqual(data["confidence"], 0.25)
        self.assertEqual(data["keywords"], [])
        self.assertEqual(data["description"], "")

    def test_plain_edit_does_not_validate(self) -> None:
        self.row.update(action="", confidence="0.3")
        result = self.process()
        assert result is not None
        data, _ = result
        self.assertEqual(data["status"], OrchestratorStatus.SEGMENT_CONFIDENCE_DONE)
        self.assertEqual(data["confidence"], 0.3)
        self.assertEqual(data["description"], "description corrigée")
        self.assertEqual(data["pipeline_target"], "TO_IA")
        self.step.assert_not_called()
