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

from cutmind.models_cm.db_models import Segment
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.logger import LoggerProtocol, ensure_logger

NULL_EQUIVALENTS = {"", "null", "none", "nan", "n/a"}

# ---------------------------------------------------------
# 🔧 Normalisations (identiques au dry-run)
# ---------------------------------------------------------


def safe_to_float(value: object) -> float:
    """Convertit proprement en float, sinon 0.0"""
    if isinstance(value, (int | float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return 0.0
    return 0.0


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


def build_new_data_from_csv_row(row: dict[str, Any]) -> dict[str, Any]:
    status = normalize_csv_value(row.get("status")) or "manual_review"
    description = normalize_csv_value(row.get("description"))
    try:
        conf = float(row.get("confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0

    # --- 🔄 Fusion des colonnes de mots-clés ---
    # Priorité à `keywords`, mais on fusionne `keywords_common` et `keywords_specific` si présentes
    raw_keywords = []
    try:
        for col in ("keywords", "keywords_common", "keywords_specific"):
            if col in row and row.get(col):
                normalized = normalize_csv_value(row.get(col))
                if normalized:
                    raw_keywords.append(normalized)

        # Joindre tout dans une seule chaîne, puis parser proprement
        merged_keywords_str = ", ".join(raw_keywords)
        keywords_list = keywords_to_list_from_str(merged_keywords_str)

        return {
            "description": description,
            "confidence": conf,
            "status": status,
            "keywords": keywords_list,
        }
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors de check_secure_in_router.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"row": row}),
        ) from exc


def compare_segment(old: Segment, new: dict[str, Any], float_epsilon: float = 1e-6) -> list[str]:
    diffs: list[str] = []

    if (old.description or "") != (new.get("description") or ""):
        diffs.append("description")

    old_conf = float(old.confidence or 0.0)
    new_conf = float(new.get("confidence") or 0.0)
    if abs(old_conf - new_conf) > float_epsilon:
        diffs.append("confidence")

    if (old.status or "") != (new.get("status") or ""):
        diffs.append("status")

    if (old.keywords or []) != (new.get("keywords") or []):
        diffs.append("keywords")

    return diffs


def write_csv_log(path: Path, rows: list[dict[str, str]]) -> None:
    """Écrit le log CSV récapitulatif."""
    with open(path, "w", newline="", encoding="utf-8") as lf:
        writer = csv.DictWriter(lf, fieldnames=["timestamp", "segment_id", "action", "differences"])
        writer.writeheader()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for r in rows:
            writer.writerow({"timestamp": now, **r})


def summarize_import(stats: dict[str, int], csv_log: Path, logger: LoggerProtocol | None = None) -> None:
    """Affiche le résumé du traitement."""
    logger = ensure_logger(logger, __name__)
    logger.info(
        "🏁 Import — %d lues, %d MAJ, %d supprimées, %d inchangées, %d erreurs",
        stats["checked"],
        stats["updated"],
        stats["deleted"],
        stats["unchanged"],
        stats["errors"],
    )
    logger.info("🧾 Log CSV → %s", csv_log)
