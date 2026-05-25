from __future__ import annotations

import random

from db.repository import CutMindRepository
from orchestrators.cutmind_or.orchestrator import CutMindOrchestratorV2
from shared.status_orchestrator.statuses import OrchestratorStatus, SegmentStatus
from shared.utils.logger import LoggerProtocol, ensure_logger
from shared.utils.settings import get_settings


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
        self.logger = logger or ensure_logger(logger, __name__)
        self.orchestrator = orchestrator or CutMindOrchestratorV2(repo=self.repo, logger=self.logger)

    def run(self, *, limit: int = 1, randomize: bool = True) -> None:
        settings = get_settings()
        router = settings.router_orchestrator

        status_mapping: list[tuple[bool, SegmentStatus]] = [
            (router.cut, OrchestratorStatus.SEGMENT_INIT),
            (router.move_post_cut, OrchestratorStatus.SEGMENT_TO_MOVE),
            (router.enhancement, OrchestratorStatus.SEGMENT_CUT_VALIDATED),
            (router.IA, SegmentStatus.ENHANCED),
            (router.confidence, OrchestratorStatus.SEGMENT_IA_DONE),
            (router.validation, OrchestratorStatus.SEGMENT_CONFIDENCE_DONE),
            (router.final_check, OrchestratorStatus.SEGMENT_VALIDATED),
        ]

        excluded_statuses_list: list[SegmentStatus] = [
            OrchestratorStatus.SEGMENT_VALIDATED_CHECK,
        ]

        for enabled, status in status_mapping:
            if not enabled:
                excluded_statuses_list.append(status)

        excluded_statuses: tuple[SegmentStatus, ...] = tuple(excluded_statuses_list)
        self.logger.debug("excluded_statuses: %s", excluded_statuses)

        if limit <= 0:
            return

        videos = self.repo.get_active_videos(excluded_statuses)

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
