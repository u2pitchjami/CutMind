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

from cutmind.models_cm.cursor_protocol import DictCursorProtocol, TupleCursorProtocol
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger

ParamsType = tuple[Any, ...] | dict[str, Any]


# -------------------------------------------------------------------
# ⚙️ Exécution sécurisée
# -------------------------------------------------------------------
@with_child_logger
def safe_execute_dict(
    cursor: DictCursorProtocol, query: str, params: ParamsType | None = None, logger: LoggerProtocol | None = None
) -> DictCursorProtocol:
    """Exécute une requête SQL sur un curseur dict avec gestion des erreurs."""
    logger = ensure_logger(logger, __name__)
    try:
        flush_dict_cursor(cursor, logger=logger)
        cursor.execute(query, params or ())
        return cursor
    except Exception as exc:
        logger.error("❌ Erreur SQL : %s", exc)
        raise exc


@with_child_logger
def safe_execute_tuple(
    cursor: TupleCursorProtocol, query: str, params: ParamsType | None = None, logger: LoggerProtocol | None = None
) -> TupleCursorProtocol:
    """Exécute une requête SQL sur un curseur tuple avec gestion des erreurs."""
    logger = ensure_logger(logger, __name__)
    try:
        flush_tuple_cursor(cursor, logger=logger)
        cursor.execute(query, params or ())
        return cursor
    except Exception as exc:
        logger.error("❌ Erreur SQL : %s", exc)
        raise exc


# -------------------------------------------------------------------
# 🧹 Flush de curseurs (multi-sets)
# -------------------------------------------------------------------


@with_child_logger
def flush_tuple_cursor(cursor: TupleCursorProtocol, logger: LoggerProtocol | None = None) -> None:
    """Vide proprement un curseur tuple (pour éviter 'Unread result found')."""
    logger = ensure_logger(logger, __name__)
    try:
        while cursor.nextset():
            pass
    except Exception as exc:
        logger.debug("Flush tuple ignoré (%s)", exc)


@with_child_logger
def flush_dict_cursor(cursor: DictCursorProtocol, logger: LoggerProtocol | None = None) -> None:
    """Vide proprement un curseur dict (pour éviter 'Unread result found')."""
    logger = ensure_logger(logger, __name__)
    try:
        while cursor.nextset():
            pass
    except Exception as exc:
        logger.debug("Flush dict ignoré (%s)", exc)
