from __future__ import annotations

from cutmind.db.repository import CutMindRepository
from cutmind.models_cm.db_models import Video
from shared.status_orchestrator.statuses import OrchestratorStatus
from shared.status_orchestrator.steps import OrchestratorStep
from shared.utils.logger import LoggerProtocol, ensure_logger


class CutMindOrchestrator:
    """
    Orchestrateur séquentiel simple.
    Chaque étape :
      - décide si elle peut s'exécuter
      - met à jour les statuts
    """

    def __init__(
        self,
        repo: CutMindRepository | None = None,
        logger: LoggerProtocol | None = None,
    ):
        self.repo = repo or CutMindRepository()
        self.logger = ensure_logger(logger, __name__)
        self.steps = self._build_steps()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, video: Video) -> None:
        self.logger.info("🎛️ Orchestration démarrée pour video %s", video.id)

        for step in self.steps:
            if step.can_run(video):
                self.logger.info("▶️ Étape déclenchée : %s", step.name)
                step.run(video)
                self.repo.update_video(video=video)
            else:
                self.logger.debug("⏭️ Étape ignorée : %s", step.name)

        self.logger.info("✅ Orchestration terminée pour video %s", video.id)

    # ------------------------------------------------------------------
    # Step registry
    # ------------------------------------------------------------------

    def _build_steps(self) -> list[OrchestratorStep]:
        return [
            OrchestratorStep(
                name="smartcut",
                can_run=self._can_run_smartcut,
                run=self._run_smartcut,
            ),
            OrchestratorStep(
                name="validate_cuts",
                can_run=self._can_run_cut_validation,
                run=self._run_cut_validation,
            ),
            OrchestratorStep(
                name="enhancement",
                can_run=self._can_run_enhancement,
                run=self._run_enhancement,
            ),
            OrchestratorStep(
                name="ia_analysis",
                can_run=self._can_run_ia,
                run=self._run_ia,
            ),
            OrchestratorStep(
                name="confidence",
                can_run=self._can_run_confidence,
                run=self._run_confidence,
            ),
            OrchestratorStep(
                name="category_validation",
                can_run=self._can_run_category_validation,
                run=self._run_category_validation,
            ),
        ]

    # ------------------------------------------------------------------
    # Conditions
    # ------------------------------------------------------------------

    def _can_run_smartcut(self, video: Video) -> bool:
        return video.status == OrchestratorStatus.VIDEO_INIT

    def _can_run_cut_validation(self, video: Video) -> bool:
        return video.status == OrchestratorStatus.SCENES_DONE

    def _can_run_enhancement(self, video: Video) -> bool:
        return video.status == OrchestratorStatus.CUT_VALIDATED

    def _can_run_ia(self, video: Video) -> bool:
        return video.status == OrchestratorStatus.ENHANCED

    def _can_run_confidence(self, video: Video) -> bool:
        return video.status == OrchestratorStatus.IA_DONE

    def _can_run_category_validation(self, video: Video) -> bool:
        return video.status == OrchestratorStatus.CONFIDENCE_DONE

    # ------------------------------------------------------------------
    # Actions (implémentations réelles à brancher)
    # ------------------------------------------------------------------

    def _run_smartcut(self, video: Video) -> None:
        self.logger.info("✂️ SmartCut pour video %s", video.id)
        # appel smartcut executor
        video.status = OrchestratorStatus.SCENES_DONE

    def _run_cut_validation(self, video: Video) -> None:
        self.logger.info("✅ Validation des cuts pour video %s", video.id)
        # validation auto / attente CSV
        video.status = OrchestratorStatus.CUT_VALIDATED

    def _run_enhancement(self, video: Video) -> None:
        self.logger.info("🎨 Enhancement ComfyUI pour video %s", video.id)
        # appel comfyui_router
        video.status = OrchestratorStatus.ENHANCED

    def _run_ia(self, video: Video) -> None:
        self.logger.info("🧠 Analyse IA pour video %s", video.id)
        # appel analyse IA
        video.status = OrchestratorStatus.IA_DONE

    def _run_confidence(self, video: Video) -> None:
        self.logger.info("📊 Calcul confidence pour video %s", video.id)
        # appel confidence engine
        video.status = OrchestratorStatus.CONFIDENCE_DONE

    def _run_category_validation(self, video: Video) -> None:
        self.logger.info("🏁 Validation catégories pour video %s", video.id)
        # validation auto / manuelle
        video.status = OrchestratorStatus.CATEGORIES_VALIDATED
