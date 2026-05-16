# check/check_enhanced_segments.py

from datetime import datetime
from pathlib import Path

from db.repository import CutMindRepository
from shared.models.db_models import Segment, Video
from shared.models.exceptions import CutMindError, ErrCode
from shared.models.timer_manager import Timer
from shared.status_orchestrator.statuses import OrchestratorStatus
from shared.utils.config import ERROR_DIR_SC, TRASH_DIR_SC
from shared.utils.error import log_exception
from shared.utils.logger import get_logger
from shared.utils.settings import get_settings
from shared.utils.trash import move_to_trash, purge_old_trash
from smartcut.executors.split_utils import move_to_error
from smartcut.services.cut_service import CutRequest, CutService


class CutWorker:
    """
    Gère l'envoi automatique des segments non conformes vers ComfyUI Router.
    """

    def __init__(self, vid: Video, segments: list[Segment]):
        self.logger = get_logger("Smartcut-Cut")
        self.video = vid
        self.segments = segments
        self.repo = CutMindRepository()
        self.service_cut = CutService()

    # ---------------------------------------------------------
    # 🚀 Main Entry Point
    # ---------------------------------------------------------
    def run(self) -> None:
        """
        Exécute un cycle complet d'envoi vers Router.

        Retourne le nombre total de segments envoyés pour traitement.
        """
        settings = get_settings()
        PURGE_DAYS = settings.smartcut.purge_days
        cut_requests = []

        for seg in self.segments:
            if not seg.id or not seg.output_path or not self.video.video_path:
                raise CutMindError(
                    "Pb vidéos.",
                    code=ErrCode.CONTEXT,
                    ctx={"segment_id": seg.id},
                )
            cut_requests.append(
                CutRequest(
                    seg_obj=seg,
                    uid=seg.uid,
                    start=seg.start,
                    end=seg.end,
                    output_path=seg.output_path,
                )
            )
            Path(seg.output_path).parent.mkdir(parents=True, exist_ok=True)
        self.logger.info("🚀 Démarrage CutWorker : %s)", self.video.name)
        if not self.video or not self.video.video_path:
            self.logger.warning("⚠️ Vidéo introuvable")
            return

        # 1️⃣ Sélectionner les vidéos concernée

        self.logger.info("🎞️ Vidéo '%s' (%d segments)", self.video.name, len(self.video.segments))

        # 3️⃣ Transaction : copie + maj DB
        with Timer(f"Traitement Cut pour la vidéo : {self.video.name}", self.logger):
            try:
                self.service_cut.cut_segments(self.video, str(self.video.video_path), cut_requests, logger=self.logger)
            except CutMindError as err:
                if self.video.tags == "" or "cut_error" not in self.video.tags:
                    self.video.add_tag_vid("cut_error")
                else:
                    error_path = move_to_error(file_path=Path(self.video.video_path), error_root=ERROR_DIR_SC)
                    self.video.video_path = str(error_path)
                    self.video.status = OrchestratorStatus.VIDEO_SMARTCUT_ERROR
                    self.logger.info(f"🗑️ Fichier déplacé vers le dossier Error : {error_path}")
                self.repo.update_video(self.video)
                self.logger.error(f"Erreur durant le cut : {err}")
                log_exception(self.logger, err)
                raise CutMindError(
                    f"❌ Erreur lors cut Smartcut {self.video.name}",
                    code=ErrCode.UNEXPECTED,
                ) from err

            # mise à jour de la session
            for seg in self.segments:
                seg.status = OrchestratorStatus.SEGMENT_CUT_DONE
                seg.pipeline_target = OrchestratorStatus.SEGMENT_IN_CUT_VALIDATION
                seg.last_updated = datetime.now().isoformat()
                self.repo.update_segment_validation(seg)

            self.video.status = OrchestratorStatus.VIDEO_CUT_DONE
            self.repo.update_video(self.video)
            self.logger.info("🎉 Tous les segments ont été coupés.")

            video_trash = move_to_trash(Path(self.video.video_path), TRASH_DIR_SC)
            self.video.video_path = str(video_trash)
            self.repo.update_video(self.video)
            purge_old_trash(TRASH_DIR_SC, days=PURGE_DAYS, logger=self.logger)
