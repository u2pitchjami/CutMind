"""
cutmind/db/db_utils.py
======================

Utilitaires sécurisés pour exécution SQL :
  - safe_execute_dict()
  - safe_execute_tuple()
  - flush_dict_cursor()
  - flush_tuple_cursor()
"""

from __future__ import annotations

import json
from typing import Any

from cutmind.models_cm.cursor_protocol import DictCursorProtocol, TupleCursorProtocol
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx

ParamsType = tuple[Any, ...] | dict[str, Any]


# -------------------------------------------------------------------
# ⚙️ Exécution sécurisée
# -------------------------------------------------------------------
def safe_execute_dict(cursor: DictCursorProtocol, query: str, params: ParamsType | None = None) -> DictCursorProtocol:
    """Exécute une requête SQL sur un curseur dict avec gestion des erreurs."""
    try:
        flush_dict_cursor(cursor)
        cursor.execute(query, params or ())
        return cursor
    except Exception as exc:
        raise CutMindError("❌ Erreur SQL", code=ErrCode.DB, ctx=get_step_ctx()) from exc


def safe_execute_tuple(
    cursor: TupleCursorProtocol, query: str, params: ParamsType | None = None
) -> TupleCursorProtocol:
    """Exécute une requête SQL sur un curseur tuple avec gestion des erreurs."""
    try:
        flush_tuple_cursor(cursor)
        cursor.execute(query, params or ())
        return cursor
    except Exception as exc:
        raise CutMindError("❌ Erreur SQL", code=ErrCode.DB, ctx=get_step_ctx()) from exc


# -------------------------------------------------------------------
# 🧹 Flush de curseurs (multi-sets)
# -------------------------------------------------------------------


def flush_tuple_cursor(cursor: TupleCursorProtocol) -> None:
    """Vide proprement un curseur tuple (pour éviter 'Unread result found')."""
    try:
        while cursor.nextset():
            pass
    except Exception as exc:
        raise CutMindError("❌ Flush tuple ignoré", code=ErrCode.DB, ctx=get_step_ctx()) from exc


def flush_dict_cursor(cursor: DictCursorProtocol) -> None:
    """Vide proprement un curseur dict (pour éviter 'Unread result found')."""
    try:
        while cursor.nextset():
            pass
    except Exception as exc:
        raise CutMindError("❌ Flush dict ignoré", code=ErrCode.DB, ctx=get_step_ctx()) from exc


def to_db_json(value: Any) -> str | None:
    return json.dumps(value) if value is not None else None
