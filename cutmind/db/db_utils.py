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

from typing import Any

from cutmind.models.cursor_protocol import DictCursorProtocol, TupleCursorProtocol
from shared.utils.logger import get_logger

logger = get_logger(__name__)

ParamsType = tuple[Any, ...] | dict[str, Any]


# -------------------------------------------------------------------
# ⚙️ Exécution sécurisée
# -------------------------------------------------------------------
def safe_execute_dict(
    cursor: DictCursorProtocol,
    query: str,
    params: ParamsType | None = None,
) -> DictCursorProtocol:
    """Exécute une requête SQL sur un curseur dict avec gestion des erreurs."""
    try:
        flush_dict_cursor(cursor)
        cursor.execute(query, params or ())
        return cursor
    except Exception as exc:
        logger.error("❌ Erreur SQL : %s", exc)
        raise exc


def safe_execute_tuple(
    cursor: TupleCursorProtocol,
    query: str,
    params: ParamsType | None = None,
) -> TupleCursorProtocol:
    """Exécute une requête SQL sur un curseur tuple avec gestion des erreurs."""
    try:
        flush_tuple_cursor(cursor)
        cursor.execute(query, params or ())
        return cursor
    except Exception as exc:
        logger.error("❌ Erreur SQL : %s", exc)
        raise exc


# -------------------------------------------------------------------
# 🧹 Flush de curseurs (multi-sets)
# -------------------------------------------------------------------


def flush_tuple_cursor(cursor: TupleCursorProtocol) -> None:
    """Vide proprement un curseur tuple (pour éviter 'Unread result found')."""
    try:
        while cursor.nextset():
            pass
    except Exception as exc:
        logger.debug("Flush tuple ignoré (%s)", exc)


def flush_dict_cursor(cursor: DictCursorProtocol) -> None:
    """Vide proprement un curseur dict (pour éviter 'Unread result found')."""
    try:
        while cursor.nextset():
            pass
    except Exception as exc:
        logger.debug("Flush dict ignoré (%s)", exc)
