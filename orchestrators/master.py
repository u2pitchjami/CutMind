import multiprocessing as mp
from multiprocessing import Process
from pathlib import Path
import time

from orchestrators.csv_validation_loop import csv_validation_loop
from orchestrators.cutmind_loop import cutmind_loop
from orchestrators.cutmind_or.launcher import VideoFlowLauncherV2
from orchestrators.smartcut_loop import back_to_imports, list_videos_and_dirs, process_smartcut_batch, smartcut_loop
from shared.models.exceptions import CutMindError
from shared.utils.config import (
    IMPORT_DIR_SC,
    MANUAL_CSV_CUT_PATH,
    MANUAL_CSV_PATH,
    WORK_DIR_SC,
)
from shared.utils.logger import LoggerProtocol, ensure_logger, get_logger
from validation.manual.update_from_csv import update_segments_csv


def run_master(logger: LoggerProtocol | None = None) -> None:
    logger = ensure_logger(logger, __name__)
    mp.set_start_method("spawn", force=True)
    logger.info("▶️ Lancement de Cutmind")
    logger.info("🎛️ Master Orchestrator démarré")

    p_smartcut = Process(
        target=smartcut_loop,
        args=(),
        daemon=True,
    )

    p_cutmind = Process(
        target=cutmind_loop,
        args=(),
        daemon=False,
    )

    p_csv = Process(
        target=csv_validation_loop,
        args=(),
        daemon=True,
    )

    # p_check = Process(
    #     target=csv_validation_loop,
    #     args=(),
    #     daemon=True,
    # )

    p_smartcut.start()
    p_cutmind.start()
    p_csv.start()
    # p_check.start() mis à la fin de cutmind mais pourrais servir un jour

    logger.info("🚀 SmartCut + CutMind + CSV loops lancés")

    p_smartcut.join()
    p_cutmind.join()
    p_csv.join()
    # p_check.join()


def run_master_test(logger: LoggerProtocol | None = None) -> None:
    logger = ensure_logger(logger, __name__)
    csv_logger = get_logger("CutMind-CSV_Validation")
    sc_logger = get_logger("CutMind-SmartCut")
    cm_logger = get_logger("CutMind_Orchestrator")
    logger.info("▶️ Lancement de Cutmind")
    logger.info("🎛️ Master Orchestrator démarré")
    from shared.models.config_manager import bootstrap_process

    bootstrap_process(logger=logger)
    from shared.utils.settings import get_settings

    settings = get_settings()
    SMARTCUT_BATCH = settings.smartcut.batch_size
    SCAN_INTERVAL = settings.smartcut.scan_interval
    SMARTCUT_ENABLED = settings.router_orchestrator.smartcut
    manual_csv_cut = Path(MANUAL_CSV_CUT_PATH)
    manual_csv_final = Path(MANUAL_CSV_PATH)

    back_to_imports(
        path_in=WORK_DIR_SC,
        path_out=IMPORT_DIR_SC,
        logger=logger,
    )

    while True:
        try:
            logger.info("🔄 Lancement d'une itération")
            # ----------------------------------------------------------
            # 1️⃣ Validation CUT (SmartCut)
            # ----------------------------------------------------------
            if manual_csv_cut.exists():
                logger.info("✂️ Traitement CSV CUT : %s", manual_csv_cut)
                csv_logger.info("✂️ Traitement CSV CUT : %s", manual_csv_cut)
                update_segments_csv(
                    status_csv="VALIDATION_CUT",
                    manual_csv=manual_csv_cut,
                    logger=csv_logger,
                )
                logger.info("✅ CSV CUT traité : %s", manual_csv_cut)
                continue

            # ----------------------------------------------------------
            # 2️⃣ Validation FINALE (IA / confidence)
            # ----------------------------------------------------------
            if manual_csv_final.exists():
                logger.info("🏁 Traitement CSV FINAL : %s", manual_csv_final)
                csv_logger.info("🏁 Traitement CSV FINAL : %s", manual_csv_final)
                update_segments_csv(
                    status_csv="VALIDATION",
                    manual_csv=manual_csv_final,
                    logger=csv_logger,
                )
                logger.info("✅ CSV FINAL traité : %s", manual_csv_final)
                continue

            if not SMARTCUT_ENABLED:
                sc_logger.info("🚫 SmartCut est désactivé dans les settings. Loop inactive.")
            else:
                videos, dirs = list_videos_and_dirs(IMPORT_DIR_SC)
                pending = len(videos) + len(dirs)
                if pending > 0:
                    logger.info("📂 Traitement SmartCut: %d éléments à traiter", pending)
                    sc_logger.info("📂 Traitement SmartCut: %d éléments à traiter", pending)
                    process_smartcut_batch(
                        videos,
                        dirs,
                        SMARTCUT_BATCH,
                        logger=sc_logger,
                    )
                    logger.info("✅ SmartCut batch traité")
                    continue

            launcher = VideoFlowLauncherV2(logger=cm_logger)
            if launcher:
                logger.info("📂 Traitement CutMind: lancement du launcher")
                cm_logger.info("📂 Traitement CutMind: lancement du launcher")
                launcher.run(limit=1)
                logger.info("✅ CutMind batch traité")
                continue

        except CutMindError:
            logger.exception("❌ Erreur Cutmind inattendue")

        except Exception:
            logger.exception("💥 Erreur inattendue CutMind")

        time.sleep(SCAN_INTERVAL)
