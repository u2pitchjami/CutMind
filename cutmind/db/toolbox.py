"""
SQL Path Migration Toolbox (Version Cutmind‑Ready)
--------------------------------------------------
Toolbox Python pour effectuer des remplacements massifs sécurisés dans une base MariaDB,
en utilisant **EXACTEMENT le flow Cutmind** :

- db_conn()
- get_dict_cursor()
- safe_execute_dict()
- logger interne Cutmind

Fonctionnalités :
    ✔ Dry‑run (aperçu sans modifier)
    ✔ Apply (mise à jour réelle)
    ✔ Rollback (restauration auto depuis backup)
    ✔ Logs propres
    ✔ Compatible pylint

Usage :
    python toolbox.py --dry-run
    python toolbox.py --apply
    python toolbox.py --rollback

Configuration à modifier en bas du fichier.
"""

import argparse

from cutmind.db.db_connection import db_conn, get_dict_cursor
from cutmind.db.db_utils import safe_execute_dict
from shared.utils.logger import get_logger

logger = get_logger("CutMind")


# ---------------------------------------------------------------------------
# CORE TOOLBOX
# ---------------------------------------------------------------------------
class PathMigrationTool:
    """Toolbox pour mise à jour sécurisée de chemins SQL en utilisant l'infra Cutmind."""

    def __init__(self, table: str, column: str, replacements: dict[str, str]):
        self.table = table
        self.column = column
        self.replacements = replacements

    # ---------------------------- BACKUP ----------------------------
    def create_backup(self) -> None:
        """Crée une table de sauvegarde (si inexistante)."""
        query = f"CREATE TABLE IF NOT EXISTS backup_{self.table}_paths AS SELECT id, {self.column} FROM {self.table};"

        try:
            with db_conn(logger=logger) as conn:
                with get_dict_cursor(conn) as cur:
                    safe_execute_dict(cur, query, logger=logger)
            logger.info("✔ Backup créée : backup_%s_paths", self.table)
        except Exception as err:  # pylint: disable=broad-except
            logger.error("Erreur lors de la création de la sauvegarde : %s", err)
            raise

    # ---------------------------- DRY RUN ---------------------------
    def dry_run(self) -> None:
        """Affiche un aperçu des modifications sans rien modifier."""
        logger.info("🔎 DRY-RUN : aperçu des remplacements")

        for old, new in self.replacements.items():
            query = (
                f"SELECT id, {self.column} AS ancien, "
                f"REPLACE({self.column}, %s, %s) AS nouveau "
                f"FROM {self.table} "
                f"WHERE {self.column} LIKE %s "
                f"LIMIT 20;"
            )

            try:
                with db_conn(logger=logger) as conn:
                    with get_dict_cursor(conn) as cur:
                        safe_execute_dict(cur, query, (old, new, f"{old}%"), logger=logger)
                        rows = cur.fetchall()

                if not rows:
                    logger.info("Aucun chemin à mettre à jour pour : %s", old)
                    continue

                logger.info("Modifications possibles pour %s → %s :", old, new)
                for row in rows:
                    logger.info("ID %s : %s → %s", row.get("id"), row.get("ancien"), row.get("nouveau"))

            except Exception as err:  # pylint: disable=broad-except
                logger.error("Erreur DRY-RUN : %s", err)
                raise

        # ---------------------------- DETECT ----------------------------

    def detect_invalid(self) -> None:
        """Détecte les chemins incorrects ou ne correspondant à aucun des préfixes attendus."""
        logger.info("🔍 Détection des chemins invalides…")

        expected_prefixes = list(self.replacements.keys())
        like_clauses = " OR ".join([f"{self.column} LIKE '{p}%'" for p in expected_prefixes])

        query = f"SELECT id, {self.column} AS path FROM {self.table} WHERE NOT ({like_clauses});"

        try:
            with db_conn(logger=logger) as conn:
                with get_dict_cursor(conn) as cur:
                    safe_execute_dict(cur, query, logger=logger)
                    rows = cur.fetchall()

            if not rows:
                logger.info("✔ Tous les chemins sont valides.")
                return

            logger.warning("⚠ Chemins inattendus détectés (%s lignes) :", len(rows))
            for row in rows[:20]:  # limiter l'affichage
                logger.warning("ID %s : %s", row.get("id"), row.get("path"))
            if len(rows) > 20:
                logger.warning("… %s autres lignes non affichées", len(rows) - 20)

        except Exception as err:  # pylint: disable=broad-except
            logger.error("Erreur lors de la détection : %s", err)
            raise

    # ---------------------------- APPLY -----------------------------
    def apply(self) -> None:
        """Applique les remplacements en masse, après backup automatique."""
        logger.info("🚀 Application des remplacements…")

        for old, new in self.replacements.items():
            query = (
                f"UPDATE {self.table} SET {self.column} = REPLACE({self.column}, %s, %s) WHERE {self.column} LIKE %s;"
            )

            try:
                with db_conn(logger=logger) as conn:
                    with get_dict_cursor(conn) as cur:
                        safe_execute_dict(cur, query, (old, new, f"{old}%"), logger=logger)
                logger.info("✔ Remplacement effectué : %s → %s", old, new)

            except Exception as err:  # pylint: disable=broad-except
                logger.error("Erreur lors de l'application : %s", err)
                raise

    # ---------------------------- ROLLBACK --------------------------
    def rollback(self) -> None:
        """Restaure toutes les valeurs depuis la table de sauvegarde."""
        logger.warning("⚠ ROLLBACK demandé — restauration en cours…")

        query = (
            f"UPDATE {self.table} t "
            f"JOIN backup_{self.table}_paths b ON t.id = b.id "
            f"SET t.{self.column} = b.{self.column};"
        )

        try:
            with db_conn(logger=logger) as conn:
                with get_dict_cursor(conn) as cur:
                    safe_execute_dict(cur, query, logger=logger)
            logger.info("✔ Rollback terminé.")
        except Exception as err:  # pylint: disable=broad-except
            logger.error("Erreur rollback : %s", err)
            raise


# ---------------------------------------------------------------------------
# MAIN EXECUTION
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SQL Path Migration Toolbox (Cutmind)")
    parser.add_argument("--dry-run", action="store_true", help="Simule les modifications")
    parser.add_argument("--apply", action="store_true", help="Applique les modifications")
    parser.add_argument("--rollback", action="store_true", help="Annule et restaure")
    parser.add_argument("--detect", action="store_true", help="Détecte les chemins invalides")
    parser.add_argument("--apply", action="store_true", help="Applique les modifications")
    parser.add_argument("--rollback", action="store_true", help="Annule et restaure")
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # CONFIG UTILISATEUR
    # ------------------------------------------------------------------
    TOOL = PathMigrationTool(
        table="segments",
        column="output_path",
        replacements={
            "/basedir/smart_cut/": "/basedir/SmartCut/",
        },
    )

    if args.rollback:
        TOOL.rollback()
    elif args.detect:
        TOOL.detect_invalid()
    elif args.apply:
        TOOL.create_backup()
        TOOL.apply()
    else:
        TOOL.dry_run()
