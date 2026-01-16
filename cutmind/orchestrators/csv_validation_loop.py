from pathlib import Path
import time

from cutmind.services.manual.update_from_csv import update_segments_csv
from shared.models.exceptions import CutMindError
from shared.utils.config import MANUAL_CSV_CUT_PATH, MANUAL_CSV_PATH
from shared.utils.logger import LoggerProtocol, ensure_logger

CSV_CHECK_INTERVAL = 30  # secondes


def csv_validation_loop(logger: LoggerProtocol | None = None) -> None:
    logger = ensure_logger(logger, __name__)
    from shared.models.config_manager import bootstrap_process

    bootstrap_process(logger=logger)
    manual_csv_cut = Path(MANUAL_CSV_CUT_PATH)
    manual_csv_final = Path(MANUAL_CSV_PATH)

    logger.info("📄 CSV validation loop démarrée")

    while True:
        try:
            # ----------------------------------------------------------
            # 1️⃣ Validation CUT (SmartCut)
            # ----------------------------------------------------------
            if manual_csv_cut.exists():
                logger.info("✂️ Traitement CSV CUT : %s", manual_csv_cut)
                update_segments_csv(
                    status_csv="VALIDATION_CUT",
                    manual_csv=manual_csv_cut,
                    logger=logger,
                )

            # ----------------------------------------------------------
            # 2️⃣ Validation FINALE (IA / confidence)
            # ----------------------------------------------------------
            if manual_csv_final.exists():
                logger.info("🏁 Traitement CSV FINAL : %s", manual_csv_final)
                update_segments_csv(
                    status_csv="VALIDATION",
                    manual_csv=manual_csv_final,
                    logger=logger,
                )

        except CutMindError:
            logger.exception("❌ Erreur métier dans csv_validation_loop")

        except Exception:
            logger.exception("💥 Erreur inattendue dans csv_validation_loop")

        time.sleep(CSV_CHECK_INTERVAL)


def wait_for_csv_update(csv_path: Path, logger: LoggerProtocol) -> None:
    if not csv_path.exists():
        logger.debug("📄 CSV inexistant, attente création")
        while not csv_path.exists():
            time.sleep(5)

    last_mtime = csv_path.stat().st_mtime
    logger.info("📄 En attente modification CSV…")

    while True:
        time.sleep(5)
        new_mtime = csv_path.stat().st_mtime
        if new_mtime > last_mtime:
            logger.info("📄 CSV modifié, relecture")
            return
