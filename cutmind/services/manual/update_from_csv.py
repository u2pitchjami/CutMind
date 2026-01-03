"""
Import réel des modifications manuelles de segments depuis CSV (v1.2)
====================================================================

Lit un CSV d'édition manuelle et met à jour la base CutMind :
 - description, confidence, status, keywords
 - gère les suppressions (status = delete / to_delete)
 - nettoie les 'None', 'NULL', etc.
"""

from __future__ import annotations

import csv
from pathlib import Path

from cutmind.db.db_connection import db_conn, get_dict_cursor
from cutmind.db.manual_db import (
    update_segment_from_csv,
)
from cutmind.db.repository import CutMindRepository
from cutmind.executors.manual.manual_utils import (
    archive_csv,
    build_new_data_from_csv_row,
    compare_segment,
    summarize_import,
    write_csv_log,
)
from cutmind.executors.manual.merge_perform import parse_merge_ids, perform_merge
from cutmind.executors.manual.recut_segment import parse_recut_points, perform_recut
from cutmind.services.main_validation import validation
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.status_orchestrator.statuses import OrchestratorStatus
from shared.utils.config import CSV_ARCHIVE_PATH, CSV_LOG_PATH, MANUAL_CSV_PATH, TRASH_DIR_SC
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from shared.utils.trash import move_to_trash, purge_old_trash


@with_child_logger
def update_segments_csv(
    status_csv: str = "manual_review",
    manual_csv: Path = Path(MANUAL_CSV_PATH),
    csv_log: Path = Path(CSV_LOG_PATH),
    logger: LoggerProtocol | None = None,
) -> None:
    """Import principal des segments CSV vers la base."""
    logger = ensure_logger(logger, __name__)
    stats = {"checked": 0, "updated": 0, "deleted": 0, "unchanged": 0, "errors": 0}
    log_rows: list[dict[str, str]] = []
    try:
        if not manual_csv.exists():
            logger.warning("❌ Erreur Fichier Manuel Absent.")
            return
        with db_conn() as conn:
            with get_dict_cursor(conn), open(manual_csv, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    seg_id = row.get("segment_id")
                    if not seg_id:
                        continue
                    stats["checked"] += 1
                    repo = CutMindRepository()
                    try:
                        video_id = repo.get_video_id_from_segment_id(int(seg_id))
                        if not video_id:
                            continue
                        video = repo.get_video_with_segments(video_id=video_id)
                        if not video:
                            continue
                        segment = next(s for s in video.segments if s.id == int(seg_id))

                        new_data = build_new_data_from_csv_row(row)
                        status = new_data["status"]

                        if status in ("delete", "to_delete"):
                            if segment.output_path:
                                old_output = Path(segment.output_path)
                                move_to_trash(file_path=old_output, trash_root=TRASH_DIR_SC)
                            repo.delete_segment(int(seg_id))
                            stats["deleted"] += 1
                            log_rows.append({"segment_id": seg_id, "action": "deleted", "differences": "ALL"})
                            continue

                        if status in ("ok", "OK"):
                            new_data["status"] = OrchestratorStatus.SEGMENT_CUT_VALIDATED
                            stats["updated"] += 1
                            log_rows.append(
                                {"segment_id": seg_id, "action": "Cut Validation OK", "differences": "status"}
                            )
                            continue

                        recut_points = parse_recut_points(status)
                        if recut_points:
                            perform_recut(segment, recut_points, logger=logger)
                            stats["updated"] += 1
                            log_rows.append(
                                {"segment_id": seg_id, "action": f"recut @{recut_points}", "differences": "recut"}
                            )
                            continue

                        merge_ids = parse_merge_ids(status)
                        if merge_ids:
                            perform_merge(segment, merge_ids, logger=logger)
                            stats["updated"] += 1
                            log_rows.append(
                                {
                                    "segment_id": seg_id,
                                    "action": f"merge with {merge_ids}",
                                    "differences": "merge",
                                }
                            )
                            continue
                        if not segment:
                            logger.warning("⚠️ Segment %s non trouvé", seg_id)
                            continue

                        diffs = compare_segment(segment, new_data)
                        if not diffs:
                            stats["unchanged"] += 1
                            log_rows.append({"segment_id": seg_id, "action": "unchanged", "differences": ""})
                            continue

                        update_segment_from_csv(segment, new_data, diffs)
                        stats["updated"] += 1
                        log_rows.append({"segment_id": seg_id, "action": "updated", "differences": ", ".join(diffs)})
                        archived_path = archive_csv(Path(MANUAL_CSV_PATH), CSV_ARCHIVE_PATH)
                        logger.info("🗄️ Fichier CSV archivé vers %s", archived_path)
                        purge_old_trash(CSV_ARCHIVE_PATH, days=60, logger=logger)

                    except Exception as exc:  # pylint: disable=broad-except
                        stats["errors"] += 1
                        logger.exception("❌ Erreur segment %s : %s", seg_id, exc)
                        log_rows.append({"segment_id": seg_id or "", "action": "error", "differences": str(exc)})

                conn.commit()

        write_csv_log(csv_log, log_rows)
        summarize_import(stats, csv_log, logger=logger)
        validation(status=status_csv, logger=logger)
    except CutMindError as err:
        raise err.with_context(get_step_ctx({"manual_csv": manual_csv})) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors du traitement du fichier csv manuel.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"manual_csv": manual_csv}),
        ) from exc
