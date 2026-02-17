from __future__ import annotations

import random

from cutmind.db.repository import CutMindRepository
from cutmind.models_cm.db_models import Segment, Video
from cutmind.services.check.check_segments import CheckSegments
from shared.models.exceptions import CutMindError, ErrCode
from shared.utils.logger import get_logger


class VideoCheckLauncher:
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
    ) -> None:
        self.repo = repo or CutMindRepository()
        self.logger = get_logger("CutMind-CheckSegments")

    def run(self, *, limit: int = 1, randomize: bool = True) -> None:
        if limit <= 0:
            return

        videos = self.repo.get_videos_by_status(status="validated")

        if not videos:
            self.logger.debug("⏸️ Aucune vidéo validated à orchestrer")
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
            if not video.id:
                raise CutMindError("❌ Erreur fichier prédit manquant pour le Check.", code=ErrCode.NOFILE)
            vid, vid_seg = self._reload_video_and_segments(video.id)
            segments = vid_seg
            self.logger.debug("🔍 Segments à déplacer post-cut : %s", [s.id for s in segments])
            if not segments:
                return

            self.logger.info(
                "🎨 Move Post Cut (%s segments) pour video %s",
                len(segments),
                video.id,
            )

            checker = CheckSegments(vid, vid_seg)
            self.logger.info(f"🔍 {checker} Segments traités avec succès.")

        self.logger.info("✅ VideoCheckLauncher terminé")

    def _reload_video_and_segments(self, video_id: int) -> tuple[Video, list[Segment]]:
        """
        Recharge la vidéo et retourne explicitement la liste des segments.
        """
        video = self.repo.get_video_with_segments(video_id=video_id)
        if video is None:
            raise ValueError(f"Video with id {video_id} not found in repository.")

        segments = list(video.segments)
        self.logger.debug(
            "🔄 Reload video %s | segments status=%s",
            video.id,
            [s.status for s in segments],
        )

        return video, segments
