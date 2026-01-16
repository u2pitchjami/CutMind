# cutmind/services/ia/ia_worker_process.py

from cutmind.models_cm.db_models import Segment, Video
from cutmind.services.ia.main_ia import IAWorker
from shared.utils.logger import LoggerProtocol, ensure_logger


def run_ia_for_video(video: Video, segments: list[Segment], logger: LoggerProtocol | None = None) -> None:
    logger = ensure_logger(logger, __name__)
    from shared.models.config_manager import bootstrap_process

    bootstrap_process(logger=logger)
    worker = IAWorker(vid=video, segments=segments)
    worker.run()
