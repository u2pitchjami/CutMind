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
from datetime import datetime
from pathlib import Path
import re
from typing import Any

from cutmind.db.db_connection import db_conn, get_dict_cursor
from cutmind.db.db_utils import safe_execute_dict
from cutmind.imports.revalidate_manual import revalidate_manual_videos
from cutmind.models.cursor_protocol import DictCursorProtocol
from shared.utils.config import CSV_LOG_PATH, MANUAL_CSV_PATH
from shared.utils.logger import get_logger

logger = get_logger(__name__)

NULL_EQUIVALENTS = {"", "null", "none", "nan", "n/a"}


# ---------------------------------------------------------
# 🔧 Normalisations (identiques au dry-run)
# ---------------------------------------------------------
def _clean_raw_str(value: str | None) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1].strip()
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_csv_value(value: str | None) -> str:
    s = _clean_raw_str(value).lower()
    if not s or re.fullmatch(r"(none|null|nan|n/a)(\s+(none|null|nan|n/a))*", s):
        return ""
    if s in NULL_EQUIVALENTS:
        return ""
    return s


def normalize_db_value(value: str) -> str:
    s = _clean_raw_str(value).lower()
    if not s or re.fullmatch(r"(none|null|nan|n/a)(\s+(none|null|nan|n/a))*", s):
        return ""
    if s in NULL_EQUIVALENTS:
        return ""
    return s


def keywords_to_list_from_str(s: str | None) -> list[str]:
    raw = s or ""
    raw_clean = _clean_raw_str(raw)
    if not raw_clean:
        return []
    tokens = [t.strip().lower() for t in re.split(r"[;,]", raw_clean) if t.strip()]
    tokens = [t for t in tokens if t not in NULL_EQUIVALENTS]
    return sorted(set(tokens))


# ---------------------------------------------------------
# 🔎 DB helpers + comparaison (identiques au dry-run)
# ---------------------------------------------------------
def get_current_segment_data(cur: DictCursorProtocol, seg_id: int) -> dict[str, str | int | float | list[str]]:
    safe_execute_dict(
        cur,
        """
        SELECT s.id, s.description, s.confidence, s.status,
               GROUP_CONCAT(k.keyword ORDER BY k.keyword SEPARATOR ', ') AS keywords
        FROM segments s
        LEFT JOIN segment_keywords sk ON sk.segment_id = s.id
        LEFT JOIN keywords k ON k.id = sk.keyword_id
        WHERE s.id=%s
        GROUP BY s.id
        """,
        (seg_id,),
    )
    row = cur.fetchone()
    if not row:
        return {}

    row_id: int = int(row.get("id") or 0)
    return {
        "id": row_id,
        "description": normalize_db_value(str(row.get("description"))),
        "confidence": float(row.get("confidence") or 0.0),
        "status": normalize_db_value(str(row.get("status"))),
        "keywords": keywords_to_list_from_str(row.get("keywords")),
    }


def build_new_data_from_csv_row(row: dict[str, Any]) -> dict[str, Any]:
    status = normalize_csv_value(row.get("status")) or "manual_review"
    description = normalize_csv_value(row.get("description"))
    try:
        conf = float(row.get("confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    keywords_str = normalize_csv_value(row.get("keywords"))
    keywords_list = keywords_to_list_from_str(keywords_str)
    return {
        "description": description,
        "confidence": conf,
        "status": status,
        "keywords": keywords_list,
    }


def compare_segment(old: dict[str, Any], new: dict[str, Any], float_epsilon: float = 1e-6) -> list[str]:
    diffs: list[str] = []

    if (old.get("description") or "") != (new.get("description") or ""):
        diffs.append("description")

    old_conf = float(old.get("confidence") or 0.0)
    new_conf = float(new.get("confidence") or 0.0)
    if abs(old_conf - new_conf) > float_epsilon:
        diffs.append("confidence")

    if (old.get("status") or "") != (new.get("status") or ""):
        diffs.append("status")

    if (old.get("keywords") or []) != (new.get("keywords") or []):
        diffs.append("keywords")

    return diffs


# ---------------------------------------------------------
# 🚀 Import réel
# ---------------------------------------------------------
def import_segments(MANUAL_CSV_PATH: Path = Path(MANUAL_CSV_PATH), CSV_LOG_PATH: Path = Path(CSV_LOG_PATH)) -> None:
    checked = updated = deleted = unchanged = errors = 0
    log_rows: list[dict[str, str]] = []

    with db_conn() as conn:
        with get_dict_cursor(conn) as cur, open(MANUAL_CSV_PATH, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:
                seg_id = row.get("segment_id")
                if not seg_id:
                    continue
                checked += 1

                try:
                    new_data = build_new_data_from_csv_row(row)
                    status = new_data["status"]

                    # --- Suppression ---
                    if status in ("delete", "to_delete"):
                        safe_execute_dict(cur, "DELETE FROM segments WHERE id=%s", (seg_id,))
                        deleted += 1
                        log_rows.append({"segment_id": seg_id, "action": "deleted", "differences": "ALL"})
                        continue

                    # --- Compare avec l'état actuel ---
                    old_data = get_current_segment_data(cur, int(seg_id))
                    if not old_data:
                        logger.warning("⚠️ Segment %s non trouvé en base", seg_id)
                        continue

                    diffs = compare_segment(old_data, new_data)
                    if not diffs:
                        unchanged += 1
                        log_rows.append({"segment_id": seg_id, "action": "unchanged", "differences": ""})
                        continue

                    # --- Mise à jour principale (description, confidence, status) ---
                    safe_execute_dict(
                        cur,
                        """
                        UPDATE segments
                        SET description=%s,
                            confidence=%s,
                            status=%s,
                            source_flow='manual_csv',
                            last_updated=NOW()
                        WHERE id=%s
                        """,
                        (
                            new_data["description"],
                            new_data["confidence"],
                            new_data["status"],
                            seg_id,
                        ),
                    )

                    # --- Mots-clés si nécessaire ---
                    if "keywords" in diffs:
                        safe_execute_dict(cur, "DELETE FROM segment_keywords WHERE segment_id=%s", (seg_id,))
                        for kw in new_data["keywords"]:
                            safe_execute_dict(cur, "SELECT id FROM keywords WHERE keyword=%s", (kw,))
                            row_kw = cur.fetchone()
                            if row_kw:
                                kw_id = row_kw["id"]
                            else:
                                safe_execute_dict(cur, "INSERT INTO keywords (keyword) VALUES (%s)", (kw,))
                                kw_id = cur.lastrowid
                            safe_execute_dict(
                                cur,
                                "INSERT INTO segment_keywords (segment_id, keyword_id) VALUES (%s, %s)",
                                (seg_id, kw_id),
                            )

                    updated += 1
                    log_rows.append(
                        {
                            "segment_id": seg_id,
                            "action": "updated",
                            "differences": ", ".join(diffs),
                        }
                    )

                except Exception as exc:  # pylint: disable=broad-except
                    errors += 1
                    logger.error("❌ Erreur segment %s : %s", seg_id, exc, exc_info=True)
                    log_rows.append(
                        {
                            "segment_id": seg_id or "",
                            "action": "error",
                            "differences": str(exc),
                        }
                    )

            conn.commit()

    # Log CSV
    with open(CSV_LOG_PATH, "w", newline="", encoding="utf-8") as lf:
        writer = csv.DictWriter(lf, fieldnames=["timestamp", "segment_id", "action", "differences"])
        writer.writeheader()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for r in log_rows:
            writer.writerow({"timestamp": now, **r})

    logger.info(
        "🏁 Import — %d lues, %d MAJ, %d supprimées, %d inchangées, %d erreurs",
        checked,
        updated,
        deleted,
        unchanged,
        errors,
    )
    logger.info("🧾 Log CSV → %s", CSV_LOG_PATH)

    logger.info("🧾 Demande de revalidation")

    revalidate_manual_videos()
