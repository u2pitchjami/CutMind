import time

from cutmind.executors.analyze.analyze_torch_utils import auto_clean_gpu
from cutmind.process.check_launch import VideoCheckLauncher
from shared.utils.logger import LoggerProtocol, ensure_logger


def check_loop(logger: LoggerProtocol | None = None) -> None:
    logger = ensure_logger(logger, __name__)
    from shared.models.config_manager import bootstrap_process

    bootstrap_process(logger=logger)
    launcher = VideoCheckLauncher()

    while True:
        try:
            launcher.run(limit=1)
            time.sleep(300)
        except Exception:
            auto_clean_gpu(logger=logger)
            logger.exception("💥 Erreur CutMind loop")
            time.sleep(300)
