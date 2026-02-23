import time

from a_orchestrators.cutmind_or.launcher import VideoFlowLauncherV2
from e_IA.keywords.utils.analyze_torch_utils import auto_clean_gpu
from shared.utils.logger import get_logger


def cutmind_loop() -> None:
    logger = get_logger("CutMind_Orchestrator")
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
