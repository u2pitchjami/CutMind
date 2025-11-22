""" """

from __future__ import annotations

from typing import Any

from cutmind.db.db_connection import db_conn, get_dict_cursor
from cutmind.db.db_utils import safe_execute_dict
from cutmind.models_cm.db_models import Segment
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger


@with_child_logger
def update_segment_from_csv(
    segment: Segment, new_data: dict[str, Any], diffs: list[str], logger: LoggerProtocol | None = None
) -> None:
    """Compare et met à jour les champs d’un segment depuis CSV."""
    logger = ensure_logger(logger, __name__)

    with db_conn(logger=logger) as conn:
        with get_dict_cursor(conn) as cur:
            safe_execute_dict(
                cur,
                """
                UPDATE segments
                SET description=%s, confidence=%s, status=%s,
                    source_flow='manual_csv', last_updated=NOW()
                WHERE id=%s
                """,
                (
                    new_data["description"],
                    new_data["confidence"],
                    new_data["status"],
                    segment.id,
                ),
                logger=logger,
            )
            conn.commit()

    if "keywords" in diffs:
        with db_conn(logger=logger) as conn:
            with get_dict_cursor(conn) as cur:
                safe_execute_dict(cur, "DELETE FROM segment_keywords WHERE segment_id=%s", (segment.id,), logger=logger)
                conn.commit()
        for kw in new_data["keywords"]:
            with db_conn(logger=logger) as conn:
                with get_dict_cursor(conn) as cur:
                    safe_execute_dict(cur, "SELECT id FROM keywords WHERE keyword=%s", (kw,), logger=logger)
                    row_kw = cur.fetchone()
            if not row_kw:
                with db_conn(logger=logger) as conn:
                    with get_dict_cursor(conn) as cur:
                        safe_execute_dict(cur, "INSERT INTO keywords (keyword) VALUES (%s)", (kw,), logger=logger)
                        kw_id = cur.lastrowid
            else:
                kw_id = row_kw["id"]

            with db_conn(logger=logger) as conn:
                with get_dict_cursor(conn) as cur:
                    safe_execute_dict(
                        cur,
                        "INSERT INTO segment_keywords (segment_id, keyword_id) VALUES (%s, %s)",
                        (segment.id, kw_id),
                        logger=logger,
                    )
                    conn.commit()

    logger.info("🟦 Segment %s mis à jour (%s)", segment.id, ", ".join(diffs))
