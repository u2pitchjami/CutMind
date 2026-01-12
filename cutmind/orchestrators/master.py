from multiprocessing import Process

from cutmind.orchestrators.csv_validation_loop import csv_validation_loop
from cutmind.orchestrators.cutmind_loop import cutmind_loop
from cutmind.orchestrators.smartcut_loop import smartcut_loop
from shared.utils.logger import LoggerProtocol, ensure_logger


def run_master(logger: LoggerProtocol | None = None) -> None:
    logger = ensure_logger(logger, __name__)
    logger.info("🎛️ Master Orchestrator démarré")

    p_smartcut = Process(
        target=smartcut_loop,
        args=(),
        daemon=True,
    )

    p_cutmind = Process(
        target=cutmind_loop,
        args=(None,),
        daemon=True,
    )

    p_csv = Process(
        target=csv_validation_loop,
        args=(None,),
        daemon=True,
    )

    p_smartcut.start()
    p_cutmind.start()
    p_csv.start()

    logger.info("🚀 SmartCut + CutMind + CSV loops lancés")

    p_smartcut.join()
    p_cutmind.join()
    p_csv.join()
