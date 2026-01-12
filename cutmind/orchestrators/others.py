"""
Import réel des modifications manuelles de segments depuis CSV (v1.2)
====================================================================

Lit un CSV d'édition manuelle et met à jour la base CutMind :
 - description, confidence, status, keywords
 - gère les suppressions (status = delete / to_delete)
 - nettoie les 'None', 'NULL', etc.
"""

from __future__ import annotations

from pathlib import Path
import time

from cutmind.services.manual.update_from_csv import update_segments_csv
from shared.status_orchestrator.statuses import OrchestratorStatus
from shared.utils.config import MANUAL_CSV_PATH
from shared.utils.logger import LoggerProtocol


def final_review_loop(logger: LoggerProtocol) -> None:
    review_csv = Path(MANUAL_CSV_PATH)
    logger.info("🔄 Démarrage loop CSV validation finale dans %s", MANUAL_CSV_PATH)

    while True:
        try:
            if not review_csv.exists():
                time.sleep(30)
                continue

            logger.info("📥 Import CSV validation finale: %s", review_csv.name)

            update_segments_csv(status_csv=OrchestratorStatus.VIDEO_PENDING_CHECK, manual_csv=review_csv, logger=logger)
            time.sleep(30)
            # archived_path = archive_csv(review_csv, CSV_ARCHIVE_PATH)
            # logger.info("🗄️ Fichier CSV archivé vers %s", archived_path)
            # purge_old_trash(CSV_ARCHIVE_PATH, days=60, logger=logger)

        except Exception:
            logger.exception("💥 Erreur loop CSV validation finale")
            time.sleep(30)
