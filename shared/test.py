from __future__ import annotations

import random

from a_orchestrators.cutmind_loop.orchestrator import CutMindOrchestratorV2
from b_db.repository import CutMindRepository
from e_IA.ia_worker_process import run_ia_for_video
from shared.models.db_models import Segment, Video
from shared.status_orchestrator.statuses import SegmentStatus
from shared.utils.logger import get_logger


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
    ) -> None:
        self.repo = repo or CutMindRepository()
        self.logger = get_logger("CutMind_Orchestrator_test")
        # self.orchestrator = orchestrator or CutMindOrchestratorV2(repo=self.repo, logger=self.logger)

    def run(self, *, limit: int = 1, randomize: bool = True) -> None:
        if limit <= 0:
            return

        videos = self.repo.get_videos_by_status(status="ready_for_ia")

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
            vid_seg = self._reload_video_with_segments(video)
            segments = [s for s in vid_seg if s.status == SegmentStatus.ENHANCED or s.pipeline_target == "IA"]
            self.logger.debug("🔍 Segments analyse ia : %s", [s.id for s in segments])
            if not segments:
                return

            run_ia_for_video(video, segments, self.logger)

            self.logger.info("🧠 IA (%s segments) pour video %s", len(segments), video.id)

        self.logger.info("✅ Launcher V2 terminé")

    def _reload_video_with_segments(self, video: Video) -> list[Segment]:
        """
        Recharge la vidéo et ses segments depuis la base de données.

        À utiliser après une étape pouvant modifier la DB hors process (IA, worker async, etc.).
        """
        fetched = self.repo.get_video_with_segments(video_id=video.id)
        if fetched is None:
            raise ValueError(f"Video with id {video.id} not found in repository.")

        segments = list(fetched.segments)
        self.logger.debug(
            "🔄 Reload video %s | segments status=%s",
            fetched.id,
            [s.status for s in segments],
        )

        return segments
