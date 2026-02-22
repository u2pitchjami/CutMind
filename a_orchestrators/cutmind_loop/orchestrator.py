from __future__ import annotations

from multiprocessing import Process

from b_db.repository import CutMindRepository
from d_comfyui_router.router_worker import RouterWorker
from e_IA.ia_worker_process import run_ia_for_video
from f_validation.main_validation import validation
from g_check.check_segments import CheckSegments
from g_check.check_status import compute_video_status
from g_check.histo.processing_checks import evaluate_segment_move
from g_check.histo.processing_log import processing_step
from shared.models.db_models import Segment, Video
from shared.models.exceptions import CutMindError, ErrCode
from shared.services.file_mover import CUTMIND_BASEDIR, FileMover, sanitize
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

        # 4️⃣ Validation finale
        self._maybe_run_final_check(video)

        # 5️⃣ Recalcul statut vidéo (projection)
        vid, _seg = self._reload_video_and_segments(video.id)
        new_status = compute_video_status(vid)
        if new_status != vid.status:
            self.logger.info(
                "🔄 Video %s statut mis à jour: %s → %s",
                vid.id,
                vid.status,
                new_status,
            )
            vid.status = new_status
            self.repo.update_video(vid)

        self.logger.info("✅ Orchestration V2 terminée pour video %s", video.id)

    # ------------------------------------------------------------------
    # Move post-cut
    # ------------------------------------------------------------------

    def _maybe_run_move(self, video: Video) -> None:
        if not video.id:
            raise CutMindError("❌ Erreur fichier prédit manquant pour le déplacement post-cut.", code=ErrCode.NOFILE)
        vid, vid_seg = self._reload_video_and_segments(video.id)
        segments = [s for s in vid_seg if s.pipeline_target == SegmentStatus.TO_MOVE]
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

        moved_ok = self.mover.move_video_files(vid, planned_targets)
        self.logger.debug("🔍 Résultat du déplacement des fichiers : %s", moved_ok)

        if not moved_ok:
            raise CutMindError(
                "Échec déplacement fichiers post-cut",
                code=ErrCode.FILE_ERROR,
            )

        # nettoyage
        for seg in segments:
            with processing_step(vid, seg, action="Move Base") as history:
                status, message = evaluate_segment_move(str(planned_targets[seg.uid]), str(CUTMIND_BASEDIR))
                history.status = status
                history.message = message
                seg.output_path = str(planned_targets[seg.uid])
                seg.pipeline_target = None
                self.repo.update_segment_validation(seg)

    # ------------------------------------------------------------------
    # Enhancement
    # ------------------------------------------------------------------

    def _maybe_run_enhancement(self, video: Video) -> None:
        vid_seg = self._reload_video_with_segments(video)
        segments = [s for s in vid_seg if s.status == SegmentStatus.CUT_VALIDATED]
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
        vid_seg = self._reload_video_with_segments(video)
        segments = [s for s in vid_seg if s.status == SegmentStatus.ENHANCED or s.pipeline_target == "IA"]
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
        vid_seg = self._reload_video_with_segments(video)
        segments = [s for s in vid_seg if s.status == SegmentStatus.IA_DONE]
        self.logger.debug("🔍 Segments confidence : %s", [s.id for s in segments])
        if not segments:
            return

        self.logger.info(
            "📊 Confidence (%s segments) pour video %s",
            len(segments),
            video.id,
        )

        # Le moteur accepte une liste → même 1 segment OK
        from e_IA.confidence.apply_confidence import (
            apply_confidence_to_session,
        )

        apply_confidence_to_session(
            session=video,
            segments=segments,
            model_name=settings.analyse_confidence.model_confidence,
        )

    # ------------------------------------------------------------------
    # Validation finale
    # ------------------------------------------------------------------

    def _maybe_run_validation(self, video: Video) -> None:
        vid_seg = self._reload_video_with_segments(video)
        segments = [s for s in vid_seg if s.status == SegmentStatus.CONFIDENCE_DONE]
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
        )

        # ⚠️ La validation peut :
        # - mettre SEGMENT_VALIDATED
        # - ou poser pipeline_target="IA" pour rework
        # self.repo.update_segments(segments)

    # ------------------------------------------------------------------
    # Final_Check
    # ------------------------------------------------------------------

    def _maybe_run_final_check(self, video: Video) -> None:
        vid_seg = self._reload_video_with_segments(video)
        segments = [s for s in vid_seg if s.status == SegmentStatus.VALIDATED]
        self.logger.debug("🔍 Segments à checker : %s", [s.id for s in segments])
        if not segments:
            return

        self.logger.info(
            "🏁 Check Final pour Validation (%s segments) pour video %s",
            len(segments),
            video.id,
        )

        checker = CheckSegments(vid=video, segments=segments)
        checker.run()

    def _reload_video_with_segments(self, video: Video) -> list[Segment]:
        """
        Recharge la vidéo et ses segments depuis la base de données.

        À utiliser après une étape pouvant modifier la DB hors process
        (IA, worker async, etc.).
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
