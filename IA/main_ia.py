# check/check_enhanced_segments.py


from transformers import PreTrainedModel, ProcessorMixin

from check.histo.processing_checks import evaluate_ia_output
from check.histo.processing_log import processing_step
from db.repository import CutMindRepository
from IA.keywords.IA_analyze import analyze_IA
from IA.keywords.prep.load_model import load_and_batches
from IA.keywords.prep.prep_analyze import cleanup_temp
from IA.keywords.utils.analyze_torch_utils import (
    ModelManager,
    release_gpu_memory,
    vram_gpu,
)
from IA.keywords.utils.keyword_normalizer import KeywordNormalizer
from shared.models.db_models import Segment, Video
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.models.timer_manager import Timer
from shared.services.gpu_guard import guard_gpu_or_requeue
from shared.status_orchestrator.statuses import SegmentStatus
from shared.utils.config import BATCH_FRAMES_DIR_SC
from shared.utils.logger import get_logger
from shared.utils.remove_empty_dirs import remove_empty_dirs
from shared.utils.settings import get_settings


class IAWorker:
    """
    Gère l'envoi automatique des segments non conformes vers ComfyUI Router.
    """

    processor: ProcessorMixin | None
    model: PreTrainedModel | None
    model_name: str | None
    batch_size: int | None
    model_precision: str | None

    def __init__(self, vid: Video, segments: list[Segment]) -> None:
        self.logger = get_logger("CutMind-Analyse_IA")
        self.video = vid
        self.segments = segments
        self.repo = CutMindRepository()
        self.model_manager = ModelManager()
        self.free_gb, self.total_gb = vram_gpu()
        self.processor = None
        self.model = None
        self.model_name = None
        self.batch_size = None
        self.model_precision = None

    # ---------------------------------------------------------
    # 🚀 Main Entry Point
    # ---------------------------------------------------------

    def run(self) -> int:
        """
        Exécute un cycle complet d'envoi vers Router.

        Retourne le nombre total de segments envoyés pour traitement.
        """
        settings = get_settings()

        model_name_key = settings.keyword_normalizer.model_name_key
        mode = settings.keyword_normalizer.mode
        similarity_threshold = settings.keyword_normalizer.similarity_threshold
        min_frames = settings.analyse_segment.min_frames_per_batch
        max_frames = settings.analyse_segment.max_frames_per_batch

        self.logger.info(
            "🚀 Démarrage IAWorker : %s",
            self.video.name,
        )

        if not self.video:
            self.logger.warning("⚠️ Vidéo introuvable")
            return 0

        processed_count = 0
        current_segment: Segment | None = None

        self.logger.info(
            "🎞️ Vidéo '%s' (%d segments)",
            self.video.name,
            len(self.video.segments),
        )

        try:
            # -------------------------------------------------
            # 1. Attendre que le GPU soit réellement disponible
            # -------------------------------------------------

            free_gb, total_gb = vram_gpu()

            self.logger.info(
                "📊 VRAM avant GPU guard : %.2f Go / %.2f Go",
                free_gb,
                total_gb,
            )

            if not guard_gpu_or_requeue(logger=self.logger):
                self.logger.warning("⚠️ GPU indisponible après expiration du GPU guard. Cycle IA abandonné.")
                return 0

            # -------------------------------------------------
            # 2. Charger le modèle uniquement APRÈS le guard
            # -------------------------------------------------

            free_gb, total_gb = vram_gpu()

            self.logger.info(
                "📊 VRAM avant chargement modèle : %.2f Go / %.2f Go",
                free_gb,
                total_gb,
            )

            (
                self.processor,
                self.model,
                self.model_name,
                self.batch_size,
                self.model_precision,
            ) = load_and_batches(
                free_gb=free_gb,
                logger=self.logger,
            )

            free_gb, total_gb = vram_gpu()

            self.logger.info(
                "📊 VRAM après chargement modèle : %.2f Go / %.2f Go",
                free_gb,
                total_gb,
            )

            # -------------------------------------------------
            # 3. Traitement IA des segments
            # -------------------------------------------------

            with Timer(
                f"Traitement IA pour la vidéo : {self.video.name}",
                self.logger,
            ):
                for seg in self.segments:
                    current_segment = seg

                    with processing_step(
                        self.video,
                        seg,
                        action="Analyse IA",
                    ) as history:
                        with Timer(
                            f"Traitement du segment : {seg.filename_predicted}",
                            self.logger,
                        ):
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
                                min_frames=min_frames,
                                max_frames=max_frames,
                                force=False,
                                logger=self.logger,
                            )

                            self.logger.info(
                                "Résultat IA : description=%s, category=%s, keywords=%s, rating=%s",
                                seg.description,
                                seg.category,
                                seg.keywords,
                                seg.rating,
                            )

                            seg.status = SegmentStatus.IA_DONE
                            seg.ai_model = self.model_name
                            seg.pipeline_target = None

                            self.logger.debug(
                                "Segment après analyse IA : %s",
                                seg,
                            )

                            self.repo.update_segment_validation(seg)

                            if not seg.id:
                                raise CutMindError(
                                    "❌ Erreur DB : aucun seg.id.",
                                    code=ErrCode.DB,
                                    ctx=get_step_ctx(
                                        {
                                            "video_name": self.video.name,
                                        }
                                    ),
                                )

                            if seg.keywords:
                                normalizer = KeywordNormalizer(
                                    model_name=model_name_key,
                                    threshold=similarity_threshold,
                                    mode=mode,
                                    logger=self.logger,
                                )

                                seg.keywords = normalizer.normalize_keywords(
                                    seg.keywords,
                                    logger=self.logger,
                                )

                                self.logger.debug(
                                    "Keywords normalisés : %s",
                                    seg.keywords,
                                )

                                self.repo.insert_keywords_standalone(
                                    segment_id=seg.id,
                                    keywords=seg.keywords,
                                )

                            if seg.hashes:
                                self.repo.replace_segment_frame_hashes(
                                    seg.id,
                                    seg.hashes,
                                )

                            processed_count += 1

                            status, message = evaluate_ia_output(seg)

                            history.status = status
                            history.message = message

                            if "ok" not in status:
                                self.logger.warning(
                                    "🚨 Segment en erreur IA : %s — %s",
                                    seg.filename_predicted,
                                    message,
                                )

                                if "IA_error" not in seg.tags:
                                    seg.add_tag("IA_error")
                                    seg.pipeline_target = SegmentStatus.TO_IA

                                    self.logger.warning("🚨 Segment en erreur IA (1ère tentative)")

                                else:
                                    seg.status = SegmentStatus.IA_ERROR
                                    seg.pipeline_target = None

                                    self.logger.warning("🚨 Segment en erreur IA (2e tentative) — statut mis à jour")

                                self.repo.update_segment_validation(seg)

                    free_gb, total_gb = vram_gpu()

                    self.logger.info(
                        "📊 VRAM après segment : %.2f Go / %.2f Go",
                        free_gb,
                        total_gb,
                    )

        except CutMindError as err:
            if current_segment is not None:
                self.handle_ia_failure(
                    current_segment,
                    err,
                )
            else:
                self.logger.error(
                    "❌ Erreur IA avant le traitement du premier segment: %s",
                    err,
                )

        except Exception as exc:
            if current_segment is not None:
                self.handle_ia_failure(
                    current_segment,
                    exc,
                    message=("❌ Erreur inattendue durant l'envoi au modèle HF."),
                    code=ErrCode.UNEXPECTED,
                )
            else:
                self.logger.exception("❌ Erreur inattendue avant le traitement du premier segment.")

        finally:
            self.logger.info("🧹 Déchargement du modèle IA...")

            # Cleanup du ModelManager existant
            self.model_manager.unload()

            # IMPORTANT : supprimer aussi les références détenues par IAWorker
            self.model = None
            self.processor = None

            # Puis libérer le cache CUDA devenu inutilisé
            release_gpu_memory(
                logger=self.logger,
            )

            free_gb, total_gb = vram_gpu()

            self.logger.info(
                "🧹 VRAM nettoyée ('full release') → VRAM libre : %.2f Go / %.2f Go",
                free_gb,
                total_gb,
            )
            # Nettoyage répertoires temporaires
            cleanup_temp()
            remove_empty_dirs(root_path=BATCH_FRAMES_DIR_SC, logger=self.logger)

        # -----------------------------------------------------
        # 5. Résultat du cycle
        # -----------------------------------------------------

        if processed_count == 0:
            self.logger.info("📭 Aucun segment traité lors de ce cycle.")
        else:
            self.logger.info(
                "✅ %d segments envoyés et traités via IA.",
                processed_count,
            )

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
            seg.pipeline_target = SegmentStatus.TO_IA
            self.logger.warning("🚨 Segment en erreur IA (1ère tentative)")
        else:
            seg.status = SegmentStatus.IA_ERROR
            seg.pipeline_target = None
            self.logger.warning("🚨 Segment en erreur IA (2e tentative) — statut mis à jour")

        self.repo.update_segment_validation(seg)

        # Enrichissement contexte global avant relance de l'erreur
        raise exc.with_context(get_step_ctx({"video.name": self.video.name, "video.status": self.video.status}))
