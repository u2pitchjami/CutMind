# check/check_enhanced_segments.py

from datetime import datetime

from cutmind.db.repository import CutMindRepository
from cutmind.models_cm.db_models import Segment, Video
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.models.timer_manager import Timer
from shared.status_orchestrator.statuses import SegmentStatus
from shared.utils.config import COLOR_RED, COLOR_RESET
from shared.utils.logger import get_logger
from shared.utils.settings import get_settings
from smartcut.services.analyze.analyze_from_cutmind import analyze_from_cutmind

settings = get_settings()

forbidden_hours = settings.router_orchestrator.forbidden_hours


class IAWorker:
    """Gère l'envoi automatique des segments non conformes vers ComfyUI Router."""

    def __init__(self, vid: Video, segments: list[Segment]):
        self.logger = get_logger("CutMind-Analyse_IA")
        self.video = vid
        self.segments = segments

    # ---------------------------------------------------------
    # 🚀 Main Entry Point
    # ---------------------------------------------------------
    def run(self) -> int:
        """
        Exécute un cycle complet d'envoi vers Router.
        Retourne le nombre total de segments envoyés pour traitement.
        """

        self.logger.info("🚀 Démarrage IAWorkerr : %s)", self.video.name)
        if not self.video:
            self.logger.warning("⚠️ Vidéo introuvable")
            return 0

        processed_count = 0

        # 1️⃣ Sélectionner les vidéos concernées
        repo = CutMindRepository()

        self.logger.info("🎞️ Vidéo '%s' (%d segments)", self.video.name, len(self.video.segments))

        # 3️⃣ Transaction : copie + maj DB
        with Timer(f"Traitement Comfyui pour la vidéo : {self.video.name}", self.logger):
            try:
                for seg in self.segments:
                    # --- DÉCISION INTELLIGENTE ---
                    current_hour = datetime.now().hour
                    router_allowed = current_hour not in forbidden_hours
                    if router_allowed:
                        with Timer(f"Traitement du segment : {seg.filename_predicted}", self.logger):
                            seg.description, seg.category, seg.keywords = analyze_from_cutmind(
                                seg=seg,
                                force=False,
                                logger=self.logger,
                            )
                            self.logger.info(
                                f"seg.description, seg.category, seg.keywords :\
                                {seg.description, seg.category, seg.keywords}"
                            )
                            seg.status = SegmentStatus.IA_DONE
                            seg.pipeline_target = None
                            repo.update_segment_validation(seg)
                            processed_count += 1
                    else:
                        self.logger.info(
                            f"{COLOR_RED}🌙 Plage horaire silencieuse — Analyse IA désactivé\
                                {COLOR_RESET}"
                        )
                        return processed_count

            except CutMindError as err:
                raise err.with_context(
                    get_step_ctx({"video.name": self.video.name, "video.status": self.video.status})
                ) from err
            except Exception as exc:
                raise CutMindError(
                    "❌ Erreur inatendue durant l'envoi à Processor Comfyui.",
                    code=ErrCode.UNEXPECTED,
                    ctx=get_step_ctx({"video.name": self.video.name, "video.status": self.video.status}),
                ) from exc

        if processed_count == 0:
            self.logger.info("📭 Aucun segment traité lors de ce cycle.")
        else:
            self.logger.info("✅ %d segments envoyés et traités via IA.", processed_count)

        self.logger.info("🏁 Cycle IA terminé.")
        return processed_count
