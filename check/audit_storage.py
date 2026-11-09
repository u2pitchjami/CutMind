"""Lancement manuel de l'audit de cohérence stockage / BDD."""

# À adapter à tes imports réels
from check.storage_reconciler import StorageReconciler
from db.repository import CutMindRepository
from shared.status_orchestrator.statuses import OrchestratorStatus
from shared.utils.config import CUTMIND_BASEDIR
from shared.utils.logger import get_logger


def run_storage_audit() -> None:
    """Lance un audit read-only des segments présents dans la base CutMind."""
    logger = get_logger(__name__)
    repo = CutMindRepository()

    try:
        segments = repo.get_segments_by_status(OrchestratorStatus.SEGMENT_VALIDATED_CHECK)

        logger.info(
            "🔎 Audit stockage : %d segment(s) validated_check",
            len(segments),
        )

        reconciler = StorageReconciler(
            base_dir=CUTMIND_BASEDIR,
            logger=logger,
        )

        reconciler.audit(segments)

    except Exception:
        logger.exception("❌ Échec de l'audit de cohérence stockage / BDD")
        raise


if __name__ == "__main__":
    run_storage_audit()
