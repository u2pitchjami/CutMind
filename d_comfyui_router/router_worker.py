"""
RouterWorker
============

Envoie automatiquement les segments 'validated' mais hors standard
(résolution < 1080p ou fps != 60) vers ComfyUI-Router.

- Sélectionne les vidéos concernées
- Copie les fichiers dans le répertoire d'import de Router
- Met à jour les statuts dans la base (segments + vidéos)
"""

from datetime import datetime
from pathlib import Path

from b_db.repository import CutMindRepository
from d_comfyui_router.models_cr.processor import VideoProcessor
from g_check.histo.processing_checks import evaluate_comfyui_output
from g_check.histo.processing_log import processing_step
from shared.models.db_models import Segment, Video
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.models.timer_manager import Timer
from shared.services.file_mover import FileMover
from shared.utils.config import COLOR_RED, COLOR_RESET, INPUT_DIR, OUTPUT_DIR
from shared.utils.logger import get_logger
from shared.utils.settings import get_settings
from shared.utils.trash import delete_files


class RouterWorker:
    """Gère l'envoi automatique des segments non conformes vers ComfyUI Router."""

    def __init__(self, vid: Video, segments: list[Segment]):
        self.logger = get_logger("CutMind-Comfyui_Router")
        self.video = vid
        self.segments = segments
        self.file_mover = FileMover()

    # ---------------------------------------------------------
    # 🚀 Main Entry Point
    # ---------------------------------------------------------
    def run(self) -> int:
        """
        Exécute un cycle complet d'envoi vers Router.
        Retourne le nombre total de segments envoyés pour traitement.
        """
        settings = get_settings()
        forbidden_hours = settings.router_orchestrator.forbidden_hours
        self.logger.info("🚀 Démarrage Router Worker")
        if not self.video:
            self.logger.warning("⚠️ Vidéo introuvable")
            return 0

        processed_count = 0
        prepared = self._prepare_segments()

        # 1️⃣ Sélectionner les vidéos concernées
        repo = CutMindRepository()

        self.logger.info("🎞️ Vidéo '%s' nb segments: %i", self.video.name, len(self.segments))

        # 3️⃣ Transaction : copie + maj DB
        with Timer(f"Traitement Comfyui pour la vidéo : {self.video.name}", self.logger):
            try:
                delete_files(path=INPUT_DIR, ext="*.mp4")

                for seg, src, dst in prepared:
                    with processing_step(self.video, seg, action="Comfyui Router") as history:
                        self.file_mover.safe_copy(src, dst)
                        seg.source_flow = "comfyui_router"
                        repo.update_segment_validation(seg)

                        # --- DÉCISION INTELLIGENTE ---
                        current_hour = datetime.now().hour
                        router_allowed = current_hour not in forbidden_hours
                        if router_allowed:
                            with Timer(f"Traitement du segment : {seg.filename_predicted}", self.logger):
                                delete_files(path=OUTPUT_DIR, ext="*.png")
                                delete_files(path=OUTPUT_DIR, ext="*.mp4")
                                processor = VideoProcessor(segment=seg, logger=self.logger)
                                new_seg = processor.process(Path(dst), logger=self.logger)
                                repo.update_segment_postprocess(new_seg)
                                self.logger.debug(f"new_seg {new_seg}")
                                processed_count += 1
                                status, message = evaluate_comfyui_output(new_seg.fps, new_seg.resolution)
                                history.status = status
                                history.message = message
                        else:
                            self.logger.info(
                                f"{COLOR_RED}🌙 Plage horaire silencieuse — Router désactivé (SmartCut forcé)\
                                    {COLOR_RESET}"
                            )
                            history.status = "ko"
                            history.message = "Plage horaire silencieuse — Analyse IA désactivé"
                            return processed_count

            except Exception as exc:
                self.logger.exception("💥 Erreur Comfyui Router")
                raise CutMindError(
                    "❌ Erreur inatendue durant l'envoi à Processor Comfyui.",
                    code=ErrCode.UNEXPECTED,
                    ctx=get_step_ctx({"video.name": self.video.name, "video.status": self.video.status}),
                ) from exc

        if processed_count == 0:
            self.logger.info("📭 Aucun segment traité lors de ce cycle.")
        else:
            self.logger.info("✅ %d segments envoyés et traités via Router.", processed_count)

        self.logger.info("🏁 Cycle RouterWorker terminé.")
        return processed_count

    # ---------------------------------------------------------
    # 🧩 Prépare les segments non conformes d'une vidéo
    # ---------------------------------------------------------

    def _prepare_segments(self) -> list[tuple[Segment, Path, Path]]:
        """Construit la liste des segments à déplacer pour Router."""
        prepared: list[tuple[Segment, Path, Path]] = []

        for seg in self.segments:
            try:
                if not seg.output_path:
                    raise ValueError(f"Segment sans chemin de sortie : {seg.uid}")
                src = Path(seg.output_path)
                dst = INPUT_DIR / src.name
                prepared.append((seg, src, dst))
                self.logger.debug("🧩 Segment à router : %s → %s", src, dst)
            except Exception as exc:
                raise CutMindError(
                    "❌ Erreur inatendue lors de la préparation du segement pour : Processor Comfyui.",
                    code=ErrCode.UNEXPECTED,
                    ctx=get_step_ctx({"seg.uid": seg.uid}),
                ) from exc
        return prepared
