""" """

from __future__ import annotations

from typing import Any

from cutmind.db.db_connection import db_conn, get_dict_cursor
from cutmind.db.db_utils import safe_execute_dict
from cutmind.models_cm.db_models import Segment
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx


def update_segment_from_csv(segment: Segment, new_data: dict[str, Any], diffs: list[str]) -> None:
    """Compare et met à jour les champs d’un segment depuis CSV."""
    try:
        with db_conn() as conn:
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
                )
                conn.commit()

        if "keywords" in diffs:
            with db_conn() as conn:
                with get_dict_cursor(conn) as cur:
                    safe_execute_dict(cur, "DELETE FROM segment_keywords WHERE segment_id=%s", (segment.id,))
                    conn.commit()
            for kw in new_data["keywords"]:
                with db_conn() as conn:
                    with get_dict_cursor(conn) as cur:
                        safe_execute_dict(cur, "SELECT id FROM keywords WHERE keyword=%s", (kw,))
                        row_kw = cur.fetchone()
                if not row_kw:
                    with db_conn() as conn:
                        with get_dict_cursor(conn) as cur:
                            safe_execute_dict(cur, "INSERT INTO keywords (keyword) VALUES (%s)", (kw,))
                            kw_id = cur.lastrowid
                else:
                    kw_id = row_kw["id"]

                with db_conn() as conn:
                    with get_dict_cursor(conn) as cur:
                        safe_execute_dict(
                            cur,
                            "INSERT INTO segment_keywords (segment_id, keyword_id) VALUES (%s, %s)",
                            (segment.id, kw_id),
                        )
                        conn.commit()
    except CutMindError as err:
        raise err.with_context(get_step_ctx({"segment_id": segment.id})) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur de la modif via CSV.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"segment_id": segment.id}),
        ) from exc
