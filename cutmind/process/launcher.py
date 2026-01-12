from __future__ import annotations

import random

from cutmind.db.repository import CutMindRepository
from shared.status_orchestrator.orchestrator import CutMindOrchestratorV2
from shared.utils.logger import LoggerProtocol, ensure_logger


class VideoFlowLauncherV2:
    """
    Launcher V2 :
    - sélectionne des vidéos actives
    - ne raisonne pas sur les statuts
    - laisse l'orchestrateur décider quoi faire
    """

    def __init__(
        self,
        *,
        repo: CutMindRepository | None = None,
        orchestrator: CutMindOrchestratorV2 | None = None,
        logger: LoggerProtocol | None = None,
    ) -> None:
        self.repo = repo or CutMindRepository()
        self.orchestrator = orchestrator or CutMindOrchestratorV2(repo=self.repo)
        self.logger = ensure_logger(logger, __name__)

    def run(self, *, limit: int = 1, randomize: bool = True) -> None:
        if limit <= 0:
            return

        videos = self.repo.get_active_videos()

        if not videos:
            self.logger.debug("⏸️ Aucune vidéo active à orchestrer")
            return

        if randomize:
            random.shuffle(videos)

        selected = videos[:limit]

        self.logger.info(
            "🚦 Launcher V2 start (%d vidéos sélectionnées)",
            len(selected),
        )

        for video in selected:
            self.logger.info("🎬 Dispatch video %s", video.uid)
            self.orchestrator.run(video)

        self.logger.info("✅ Launcher V2 terminé")
