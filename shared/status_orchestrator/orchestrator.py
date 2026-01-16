from __future__ import annotations

from multiprocessing import Process

from cutmind.db.repository import CutMindRepository
from cutmind.models_cm.db_models import Video
from cutmind.process.file_mover import CUTMIND_BASEDIR, FileMover, sanitize
from cutmind.process.router_worker import RouterWorker
from cutmind.services.check.check_status import compute_video_status
from cutmind.services.ia.ia_worker_process import run_ia_for_video
from cutmind.services.main_validation import validation
from shared.models.exceptions import CutMindError, ErrCode
from shared.status_orchestrator.statuses import SegmentStatus
from shared.utils.logger import LoggerProtocol, ensure_logger
from shared.utils.settings import get_settings


class CutMindOrchestratorV2:
    """
    Orchestrateur CutMind V2 — segment-centric.

    - Les décisions se basent sur les segments
    - Le statut vidéo est une projection recalculée
    - pipeline_target permet le rework ciblé
    """

    def __init__(
        self,
        repo: CutMindRepository | None = None,
        logger: LoggerProtocol | None = None,
    ):
        self.repo = repo or CutMindRepository()
        self.mover = FileMover()
        self.logger = ensure_logger(logger, __name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, video: Video) -> None:
        if not video or not video.id:
            raise ValueError("Video must have an ID to run the orchestrator.")
        self.logger.info("🎛️ Orchestration V2 démarrée pour video %s", video.id)
        fetched = self.repo.get_video_with_segments(video_id=video.id)
        if fetched is None:
            raise ValueError(f"Video with id {video.id} not found in repository.")
        video = fetched
        segments = list(video.segments)
        self.logger.debug("🔍 Segments : %s", [s.status for s in segments])

        # 1️⃣ Move post-cut
        self._maybe_run_move(video)

        # 1️⃣ Enhancement
        self._maybe_run_enhancement(video)

        # 2️⃣ IA
        self._maybe_run_ia(video)

        # 3️⃣ Confidence
        self._maybe_run_confidence(video)

        # 4️⃣ Validation finale
        self._maybe_run_validation(video)

        # 5️⃣ Recalcul statut vidéo (projection)
        new_status = compute_video_status(video)
        if new_status != video.status:
            self.logger.info(
                "🔄 Video %s statut mis à jour: %s → %s",
                video.id,
                video.status,
                new_status,
            )
            video.status = new_status
            self.repo.update_video(video)

        self.logger.info("✅ Orchestration V2 terminée pour video %s", video.id)

    # ------------------------------------------------------------------
    # Move post-cut
    # ------------------------------------------------------------------

    def _maybe_run_move(self, video: Video) -> None:
        segments = [s for s in video.segments if s.pipeline_target == SegmentStatus.TO_MOVE]
        self.logger.debug("🔍 Segments à déplacer post-cut : %s", [s.id for s in segments])
        if not segments:
            return

        self.logger.info(
            "🎨 Move Post Cut (%s segments) pour video %s",
            len(segments),
            video.id,
        )
        # Plan des destinations (relatives)
        planned_targets = {}
        safe_name = sanitize(video.name)
        for seg in segments:
            if not seg.filename_predicted:
                raise CutMindError(
                    "❌ Erreur fichier prédit manquant pour le déplacement post-cut.", code=ErrCode.NOFILE
                )
            dst_final = CUTMIND_BASEDIR / safe_name / seg.filename_predicted
            dst_rel = dst_final
            planned_targets[seg.uid] = dst_rel

        moved_ok = self.mover.move_video_files(video, planned_targets)
        self.logger.debug("🔍 Résultat du déplacement des fichiers : %s", moved_ok)

        if not moved_ok:
            raise CutMindError(
                "Échec déplacement fichiers post-cut",
                code=ErrCode.FILE_ERROR,
            )

        # nettoyage
        for seg in segments:
            seg.output_path = str(planned_targets[seg.uid])
            seg.pipeline_target = None
            self.repo.update_segment_validation(seg)

    # ------------------------------------------------------------------
    # Enhancement
    # ------------------------------------------------------------------

    def _maybe_run_enhancement(self, video: Video) -> None:
        segments = [s for s in video.segments if s.status == SegmentStatus.CUT_VALIDATED]
        self.logger.debug("🔍 Segments à enhanced : %s", [s.id for s in segments])
        if not segments:
            return

        self.logger.info(
            "🎨 Enhancement (%s segments) pour video %s",
            len(segments),
            video.id,
        )

        worker = RouterWorker(vid=video, segments=segments)
        worker.run()

    # ------------------------------------------------------------------
    # IA
    # ------------------------------------------------------------------

    def _maybe_run_ia(self, video: Video) -> None:
        segments = [s for s in video.segments if s.status == SegmentStatus.ENHANCED or s.pipeline_target == "IA"]
        self.logger.debug("🔍 Segments analyse ia : %s", [s.id for s in segments])
        if not segments:
            return

        self.logger.info("🧠 IA (%s segments) pour video %s", len(segments), video.id)

        # --- Process GPU isolé ---
        p = Process(target=run_ia_for_video, args=(video, segments, self.logger), daemon=False)
        p.start()
        p.join()

    # ------------------------------------------------------------------
    # Confidence
    # ------------------------------------------------------------------

    def _maybe_run_confidence(self, video: Video) -> None:
        settings = get_settings()
        segments = [s for s in video.segments if s.status == SegmentStatus.IA_DONE]
        self.logger.debug("🔍 Segments confidence : %s", [s.id for s in segments])
        if not segments:
            return

        self.logger.info(
            "📊 Confidence (%s segments) pour video %s",
            len(segments),
            video.id,
        )

        # Le moteur accepte une liste → même 1 segment OK
        from smartcut.services.analyze.apply_confidence import (
            apply_confidence_to_session,
        )

        apply_confidence_to_session(
            session=video,
            segments=segments,
            model_name=settings.analyse_confidence.model_confidence,
            logger=self.logger,
        )

    # ------------------------------------------------------------------
    # Validation finale
    # ------------------------------------------------------------------

    def _maybe_run_validation(self, video: Video) -> None:
        segments = [s for s in video.segments if s.status == SegmentStatus.CONFIDENCE_DONE]
        self.logger.debug("🔍 Segments à valider : %s", [s.id for s in segments])
        if not segments:
            return

        self.logger.info(
            "🏁 Validation (%s segments) pour video %s",
            len(segments),
            video.id,
        )

        # Validation auto / manuelle via CSV
        validation(
            vid=video,
            segments=segments,
            status=SegmentStatus.CONFIDENCE_DONE,
            logger=self.logger,
        )

        # ⚠️ La validation peut :
        # - mettre SEGMENT_VALIDATED
        # - ou poser pipeline_target="IA" pour rework
        # self.repo.update_segments(segments)
