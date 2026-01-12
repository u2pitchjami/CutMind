import time

from cutmind.process.launcher import VideoFlowLauncherV2
from shared.utils.logger import LoggerProtocol, ensure_logger


def cutmind_loop(logger: LoggerProtocol | None = None) -> None:
    logger = ensure_logger(logger, __name__)
    launcher = VideoFlowLauncherV2(logger=logger)

    while True:
        try:
            launcher.run(limit=1)
            time.sleep(20)
        except Exception:
            logger.exception("💥 Erreur CutMind loop")
            time.sleep(30)
