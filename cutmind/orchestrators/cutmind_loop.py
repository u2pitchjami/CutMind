import time

from cutmind.process.launcher import VideoFlowLauncherV2
from shared.utils.logger import LoggerProtocol, ensure_logger
from smartcut.executors.analyze.analyze_torch_utils import auto_clean_gpu


def cutmind_loop(logger: LoggerProtocol | None = None) -> None:
    logger = ensure_logger(logger, __name__)
    from shared.models.config_manager import bootstrap_process

    bootstrap_process(logger=logger)
    launcher = VideoFlowLauncherV2(logger=logger)

    while True:
        try:
            launcher.run(limit=1)
            time.sleep(20)
        except Exception:
            auto_clean_gpu(logger=logger)
            logger.exception("💥 Erreur CutMind loop")
            time.sleep(30)
