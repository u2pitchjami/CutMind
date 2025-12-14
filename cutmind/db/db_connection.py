"""
cutmind/db/db_connection.py
===========================

Outils centralisés pour la gestion des connexions MySQL/MariaDB :
  - get_db_connection()
  - get_dict_cursor()
  - get_tuple_cursor()
  - db_conn() (context manager pratique)

Dépend de :
  - cutmind.models_cm.db_config (DB_CONFIG)
  - cutmind.utils.logger
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

import pymysql
from pymysql.connections import Connection
from pymysql.cursors import DictCursor

from cutmind.models_cm.cursor_protocol import DictCursorProtocol, TupleCursorProtocol
from cutmind.models_cm.db_config import DB_CONFIG
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.logger import get_logger

logger = get_logger(__name__)


# -------------------------------------------------------------------
# 🔌 Connexion principale
# -------------------------------------------------------------------
def get_db_connection() -> Connection:
    """
    Ouvre une connexion MySQL/MariaDB avec gestion d’erreurs et logs.
    """
    try:
        conn = pymysql.connect(**DB_CONFIG)
        return conn
    except pymysql.MySQLError as exc:
        raise CutMindError("❌ Échec connexion DB", code=ErrCode.DB, ctx=get_step_ctx()) from exc


# -------------------------------------------------------------------
# 🎯 Curseurs typés
# -------------------------------------------------------------------
def get_dict_cursor(conn: Connection) -> DictCursorProtocol:
    """
    Retourne un curseur dict (clé = nom de colonne)
    """
    return cast(DictCursorProtocol, conn.cursor(DictCursor))


def get_tuple_cursor(conn: Connection) -> TupleCursorProtocol:
    """
    Retourne un curseur tuple (index numérique)
    """
    return cast(TupleCursorProtocol, conn.cursor())


# -------------------------------------------------------------------
# ⚙️ Context manager complet
# -------------------------------------------------------------------


@contextmanager
def db_conn(*, autocommit: bool = False) -> Iterator[Connection]:
    conn = get_db_connection()
    conn.autocommit(autocommit)

    try:
        yield conn
        if not autocommit:
            conn.commit()

    except Exception as exc:
        # 🔥 LOG COMPLET AVANT DE WRAPPER
        logger.exception(
            "DB error occurred",
            extra={
                "exc_type": type(exc).__name__,
                "exc_args": getattr(exc, "args", None),
            },
        )

        if not autocommit:
            try:
                conn.rollback()
            except Exception:
                logger.exception("Rollback failed")

        raise CutMindError(
            "DB: SQL execution failed",
            code=ErrCode.DB,
            ctx=get_step_ctx(
                {
                    "db_error_type": type(exc).__name__,
                }
            ),
        ) from exc

    finally:
        try:
            conn.close()
        except pymysql.err.Error as close_exc:
            if "Already closed" not in str(close_exc):
                logger.exception("Error closing DB connection")
