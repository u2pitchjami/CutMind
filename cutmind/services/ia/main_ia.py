# check/check_enhanced_segments.py

from datetime import datetime

from transformers import PreTrainedModel, ProcessorMixin

from cutmind.db.repository import CutMindRepository
from cutmind.executors.analyze.analyze_torch_utils import (
    release_gpu_memory,
    vram_gpu,
)
from cutmind.executors.check.processing_checks import evaluate_ia_output
from cutmind.executors.check.processing_log import processing_step
from cutmind.executors.ia.load_model import load_and_batches
from cutmind.models_cm.db_models import Segment, Video
from cutmind.services.analyze.IA_analyze import analyze_IA
from cutmind.services.keyword_normalizer import KeywordNormalizer
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.models.timer_manager import Timer
from shared.status_orchestrator.statuses import SegmentStatus
from shared.utils.config import COLOR_RED, COLOR_RESET
from shared.utils.logger import get_logger
from shared.utils.settings import get_settings


class IAWorker:
    processor: ProcessorMixin
    model: PreTrainedModel
    model_name: str
    batch_size: int
    model_precision: str
    """Gère l'envoi automatique des segments non conformes vers ComfyUI Router."""

    def __init__(self, vid: Video, segments: list[Segment]):
        self.logger = get_logger("CutMind-Analyse_IA")
        self.video = vid
        self.segments = segments
        self.repo = CutMindRepository()
        self.free_gb, self.total_gb = vram_gpu()
        self.processor, self.model, self.model_name, self.batch_size, self.model_precision = load_and_batches(
            free_gb=self.free_gb, logger=self.logger
        )

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
        MODEL_NAME = settings.keyword_normalizer.model_name_key
        MODE = settings.keyword_normalizer.mode
        SIMILARITY_THRESHOLD = settings.keyword_normalizer.similarity_threshold
        self.logger.info("🚀 Démarrage IAWorkerr : %s)", self.video.name)
        if not self.video:
            self.logger.warning("⚠️ Vidéo introuvable")
            return 0

        processed_count = 0

        # 1️⃣ Sélectionner les vidéos concernée

        self.logger.info("🎞️ Vidéo '%s' (%d segments)", self.video.name, len(self.video.segments))

        # Chargement du modèle IA + paramètres de batching
        free_gb, total_gb = vram_gpu()
        self.logger.info(f"📊 VRAM avant chargement : {free_gb:.2f} Go / {total_gb:.2f} Go")

        # 3️⃣ Transaction : copie + maj DB
        with Timer(f"Traitement IA pour la vidéo : {self.video.name}", self.logger):
            try:
                for seg in self.segments:
                    with processing_step(self.video, seg, action="Analyse IA") as history:
                        # --- DÉCISION INTELLIGENTE ---
                        current_hour = datetime.now().hour
                        IA_allowed = current_hour not in forbidden_hours
                        if IA_allowed:
                            with Timer(f"Traitement du segment : {seg.filename_predicted}", self.logger):
                                (
                                    seg.description,
                                    seg.category,
                                    seg.keywords,
                                    seg.quality_score,
                                    seg.rating,
                                    seg.hashes,
                                ) = analyze_IA(
                                    seg=seg,
                                    processor=self.processor,
                                    model=self.model,
                                    model_precision=self.model_precision,
                                    model_name=self.model_name,
                                    batch_size=self.batch_size,
                                    force=False,
                                    logger=self.logger,
                                )
                                self.logger.info(
                                    f"seg.description, seg.category, seg.keywords, seg.rating :\
                                {seg.description, seg.category, seg.keywords, seg.rating}"
                                )
                                seg.status = SegmentStatus.IA_DONE
                                seg.ai_model = self.model_name
                                seg.pipeline_target = None
                                self.logger.debug(f"segment : {seg}")
                                self.repo.update_segment_validation(seg)

                                if not seg.id:
                                    raise CutMindError(
                                        "❌ Erreur DB : aucun seg.id.",
                                        code=ErrCode.DB,
                                        ctx=get_step_ctx({"video_name": self.video.name}),
                                    )
                                if seg.keywords:
                                    normalizer = KeywordNormalizer(
                                        model_name=MODEL_NAME, threshold=SIMILARITY_THRESHOLD, mode=MODE
                                    )
                                    seg.keywords = normalizer.normalize_keywords(seg.keywords)
                                    self.logger.debug(f"keywords : {seg.keywords}")
                                    self.repo.insert_keywords_standalone(segment_id=seg.id, keywords=seg.keywords)

                                if seg.hashes:
                                    self.repo.replace_segment_frame_hashes(seg.id, seg.hashes)

                                processed_count += 1
                                status, message = evaluate_ia_output(seg)
                                history.status = status
                                history.message = message
                        else:
                            self.logger.info(
                                f"{COLOR_RED}🌙 Plage horaire silencieuse — Analyse IA désactivé\
                                    {COLOR_RESET}"
                            )
                            history.status = "ko"
                            history.message = "Plage horaire silencieuse — Analyse IA désactivé"
                            return processed_count

                    free, total = vram_gpu()
                    self.logger.info(f"📊 VRAM avant release : {free:.2f} Go / {total:.2f} Go")

            except CutMindError as err:
                self.handle_ia_failure(seg, err)

            except Exception as exc:
                self.handle_ia_failure(
                    seg,
                    exc,
                    message="❌ Erreur inattendue durant l'envoi à Processor Comfyui.",
                    code=ErrCode.UNEXPECTED,
                )

        release_gpu_memory(model=self.model, processor=self.processor, cache_only=False, logger=self.logger)
        free, total = vram_gpu()
        self.logger.info(f"🧹 VRAM nettoyée ('full release') → VRAM libre : {free:.2f} Go / {total:.2f} Go")

        if processed_count == 0:
            self.logger.info("📭 Aucun segment traité lors de ce cycle.")
        else:
            self.logger.info("✅ %d segments envoyés et traités via IA.", processed_count)

        self.logger.info("🏁 Cycle IA terminé.")
        return processed_count

    def handle_ia_failure(
        self, seg: Segment, exc: Exception, message: str | None = None, code: ErrCode = ErrCode.IAERROR
    ) -> None:
        """
        Gère une erreur IA en centralisant la logique de tag, statut et contexte enrichi.
        Lève toujours une CutMindError enrichie du contexte vidéo.
        """

        # Convertit exc en CutMindError si ce n’en est pas déjà une
        if not isinstance(exc, CutMindError):
            exc = CutMindError(
                message or "Erreur IA",
                code=code,
                ctx=get_step_ctx({"video.name": self.video.name, "video.status": self.video.status}),
            )
            raise exc from exc  # ce "from exc" va utiliser l'ancien `exc` comme cause

        # Gestion des tags / statut segment
        if "IA_error" not in seg.tags:
            seg.add_tag("IA_error")
            self.logger.warning("🚨 Segment en erreur IA (1ère tentative)")
        else:
            seg.status = SegmentStatus.IA_ERROR
            self.logger.warning("🚨 Segment en erreur IA (2e tentative) — statut mis à jour")

        self.repo.update_segment_validation(seg)

        # Enrichissement contexte global avant relance de l'erreur
        raise exc.with_context(get_step_ctx({"video.name": self.video.name, "video.status": self.video.status}))
