"""
cutmind/db/db_connection.py
===========================

Outils centralisés pour la gestion des connexions MySQL/MariaDB :
  - get_db_connection()
  - get_dict_cursor()
  - get_tuple_cursor()
  - db_conn() (context manager pratique)

Dépend de :
  - cutmind.models.db_config (DB_CONFIG)
  - cutmind.utils.logger
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

import pymysql
from pymysql.connections import Connection
from pymysql.cursors import DictCursor

from cutmind.models.cursor_protocol import DictCursorProtocol, TupleCursorProtocol
from cutmind.models.db_config import DB_CONFIG
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
        logger.debug("✅ Connexion DB ouverte : %s@%s:%s", DB_CONFIG["user"], DB_CONFIG["host"], DB_CONFIG["port"])
        return conn
    except pymysql.MySQLError as exc:
        logger.error("❌ Échec connexion DB : %s", exc)
        raise exc


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
    """
    Ouvre une connexion, gère commit/rollback/close automatiquement.

    Exemple :
        with db_conn() as conn:
            with get_dict_cursor(conn) as cur:
                cur.execute("SELECT * FROM videos LIMIT 5")
                rows = cur.fetchall()
    """
    conn = get_db_connection()
    conn.autocommit(autocommit)
    try:
        yield conn
        if not autocommit:
            conn.commit()
    except Exception as exc:
        if not autocommit:
            try:
                conn.rollback()
                logger.warning("↩️ Transaction annulée : %s", exc)
            except Exception as rb_exc:  # pylint: disable=broad-except
                logger.error("⚠️ Rollback impossible : %s", rb_exc)
        raise
    finally:
        try:
            conn.close()
            logger.debug("🔒 Connexion DB fermée")
        except pymysql.err.Error as close_exc:
            if "Already closed" not in str(close_exc):
                logger.warning("⚠️ Erreur fermeture connexion : %s", close_exc)
