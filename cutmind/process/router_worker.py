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

from comfyui_router.models_cr.processor import VideoProcessor
from cutmind.db.repository import CutMindRepository
from cutmind.models_cm.db_models import Segment, Video
from cutmind.process.file_mover import FileMover
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.models.timer_manager import Timer
from shared.utils.config import CM_NB_VID_ROUTER, COLOR_RED, COLOR_RESET, INPUT_DIR, OUTPUT_DIR
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from shared.utils.settings import get_settings
from shared.utils.trash import delete_files

settings = get_settings()

forbidden_hours = settings.router_orchestrator.forbidden_hours


class RouterWorker:
    """Gère l'envoi automatique des segments non conformes vers ComfyUI Router."""

    @with_child_logger
    def __init__(self, limit_videos: int = CM_NB_VID_ROUTER, logger: LoggerProtocol | None = None):
        logger = ensure_logger(logger, __name__)
        self.repo = CutMindRepository()
        self.limit_videos = limit_videos
        self.file_mover = FileMover()

    # ---------------------------------------------------------
    # 🚀 Main Entry Point
    # ---------------------------------------------------------
    @with_child_logger
    def run(self, logger: LoggerProtocol | None = None) -> int:
        """
        Exécute un cycle complet d'envoi vers Router.
        Retourne le nombre total de segments envoyés pour traitement.
        """
        logger = ensure_logger(logger, __name__)

        logger.info("🚀 Démarrage RouterWorker (max %d vidéos)", self.limit_videos)

        processed_count = 0

        # 1️⃣ Sélectionner les vidéos concernées
        video_uids = self.repo.get_nonstandard_videos(self.limit_videos)
        if not video_uids:
            logger.info("📭 Aucun segment non standard trouvé — base à jour.")
            return 0

        logger.info("🎬 %d vidéos candidates détectées", len(video_uids))

        # 2️⃣ Parcourir les vidéos et segments
        for uid in video_uids:
            video = self.repo.get_video_with_segments(uid)
            if not video:
                logger.warning("⚠️ Vidéo UID introuvable : %s", uid)
                continue

            logger.info("🎞️ Vidéo '%s' (%d segments)", video.name, len(video.segments))

            # Sélectionne les segments hors standard
            prepared = self._prepare_segments(video, logger=logger)

            if not prepared:
                logger.info("ℹ️ Tous les segments de %s sont conformes.", video.name)
                video.status = "validated"
                self.repo.update_video(video)
                continue

            # 3️⃣ Transaction : copie + maj DB
            with Timer(f"Traitement Comfyui pour la vidéo : {video.name}", logger):
                try:
                    with self.repo.transaction() as conn:
                        video.status = "processing_router"
                        self.repo.update_video(video, conn)

                        for seg, src, dst in prepared:
                            self.file_mover.safe_copy(src, dst)
                            seg.status = "in_router"
                            seg.source_flow = "comfyui_router"
                            self.repo.update_segment_validation(seg, conn)

                    for _seg, _src, dst in prepared:
                        # --- DÉCISION INTELLIGENTE ---
                        current_hour = datetime.now().hour
                        router_allowed = current_hour not in forbidden_hours
                        if router_allowed:
                            with Timer(f"Traitement du segment : {seg.filename_predicted}", logger):
                                delete_files(path=OUTPUT_DIR, ext="*.png")
                                delete_files(path=OUTPUT_DIR, ext="*.mp4")
                                repo = CutMindRepository()
                                processor = VideoProcessor(segment=seg, logger=logger)
                                new_seg = processor.process(Path(dst), logger=logger)
                                repo.update_segment_postprocess(new_seg)
                                processed_count += 1
                        else:
                            logger.info(
                                f"{COLOR_RED}🌙 Plage horaire silencieuse — Router désactivé (SmartCut forcé)\
                                    {COLOR_RESET}"
                            )
                            video.status = "validated"
                            self.repo.update_video(video)
                            return processed_count

                    video.status = "enhanced"
                    self.repo.update_video(video)

                    logger.info("📬 Vidéo %s envoyée vers Router (%d segments).", video.uid, len(prepared))

                except CutMindError as err:
                    raise err.with_context(
                        get_step_ctx({"video.name": video.name, "video.status": video.status})
                    ) from err
                except Exception as exc:
                    raise CutMindError(
                        "❌ Erreur inatendue durant l'envoi à Processor Comfyui.",
                        code=ErrCode.UNEXPECTED,
                        ctx=get_step_ctx({"video.name": video.name, "video.status": video.status}),
                    ) from exc

        if processed_count == 0:
            logger.info("📭 Aucun segment traité lors de ce cycle.")
        else:
            logger.info("✅ %d segments envoyés et traités via Router.", processed_count)

        logger.info("🏁 Cycle RouterWorker terminé.")
        return processed_count

    # ---------------------------------------------------------
    # 🧠 Vérifie quels segments doivent être routés
    # ---------------------------------------------------------
    @staticmethod
    def _needs_routing(seg: Segment) -> bool:
        """Retourne True si le segment est hors standard (résolution/fps)."""
        try:
            width, height = (int(x) for x in (seg.resolution or "0x0").split("x"))
        except ValueError:
            return True

        if width < 1920 or height < 1080:
            return True
        if seg.fps is None or seg.fps != 60.0:
            return True
        return False

    # ---------------------------------------------------------
    # 🧩 Prépare les segments non conformes d'une vidéo
    # ---------------------------------------------------------
    @with_child_logger
    def _prepare_segments(self, video: Video, logger: LoggerProtocol | None = None) -> list[tuple[Segment, Path, Path]]:
        """Construit la liste des segments à déplacer pour Router."""
        logger = ensure_logger(logger, __name__)
        prepared: list[tuple[Segment, Path, Path]] = []

        for seg in video.segments:
            if self._needs_routing(seg):
                try:
                    if not seg.output_path:
                        raise ValueError(f"Segment sans chemin de sortie : {seg.uid}")
                    src = Path(seg.output_path)
                    dst = INPUT_DIR / src.name
                    prepared.append((seg, src, dst))
                    logger.debug("🧩 Segment à router : %s → %s", src, dst)
                except Exception as exc:
                    raise CutMindError(
                        "❌ Erreur inatendue lors de la préparation du segement pour : Processor Comfyui.",
                        code=ErrCode.UNEXPECTED,
                        ctx=get_step_ctx({"seg.uid": seg.uid}),
                    ) from exc
        return prepared
