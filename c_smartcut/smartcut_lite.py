"""
smart_multicut_lite.py — Orchestrateur SmartCut-Lite
====================================================
- Conçu pour des dossiers de segments déjà découpés
- Pas de pyscenedetect / merge / cut vidéo
- Garde le même format JSON SmartCut pour intégration Cutmind
"""

from __future__ import annotations

from pathlib import Path
import shutil
import uuid

from b_db.repository import CutMindRepository
from c_smartcut.lite.load_segments import load_segments_from_directory
from c_smartcut.lite.relocate_and_rename_segments import relocate_and_rename_segments
from shared.models.db_models import Video
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.status_orchestrator.statuses import OrchestratorStatus
from shared.utils.logger import LoggerProtocol, ensure_logger


def lite_cut(directory_path: Path, logger: LoggerProtocol | None = None) -> None:
    """
    Pipeline simplifié SmartCut pour segments déjà coupés.
    Args:
        directory_path: Dossier contenant les segments vidéo (.mp4/.mkv)
    """
    logger = ensure_logger(logger, __name__)
    try:
        repo = CutMindRepository()
        logger.info("🚀 Démarrage SmartCut-Lite sur : %s", directory_path)
        if any(directory_path.iterdir()):
            # Étape 0️⃣ — Initialisation session
            session = repo.video_exists_by_video_path(str(directory_path))
            if not session:
                new_vid = Video(
                    uid=str(uuid.uuid4()),
                    name=directory_path.name,
                    video_path=str(directory_path),
                    status=OrchestratorStatus.VIDEO_INIT,
                    origin="smartcut_lite",
                )
                repo.insert_video_with_segments(new_vid)
                vid = repo.get_video_with_segments(video_uid=new_vid.uid)
            else:
                vid = repo.get_video_with_segments(video_id=session)
                if not vid or not vid.status:
                    raise CutMindError(
                        f"Vidéo introuvable en base de données pour l'ID {session}",
                        code=ErrCode.NOT_FOUND,
                    )
                logger.info("♻️ Reprise de session existante %s : %s", vid.name, vid.status)
            if not vid:
                raise Exception("Impossible de créer ou récupérer la vidéo SmartCut-Lite.")

            load_segments_from_directory(vid, directory_path, logger=logger)

            vid.status = "scenes_done"
            repo.update_video(vid)

            vid = repo.get_video_with_segments(video_uid=vid.uid)
            if not vid or not vid.status:
                raise Exception("Impossible de récupérer la vidéo SmartCut-Lite après chargement des segments.")

            logger.info("💾 Session initialisée (%d segments).", len(vid.segments))

            # Étape 3️⃣ — Finalisation
            logger.info("📊 Déplacement des fichiers")
            relocate_and_rename_segments(session=vid, logger=logger)
            vid.status = OrchestratorStatus.VIDEO_CUT_DONE
            repo.update_video(vid)
            logger.info("🏁 SmartCut-Lite terminé pour %s", directory_path)

            vid = repo.get_video_with_segments(video_uid=vid.uid)
            if not vid or not vid.status:
                raise Exception("Impossible de récupérer la vidéo SmartCut-Lite après chargement des segments.")

        else:
            logger.debug(f"🧹 Le dossier {directory_path} est vide.")

        if directory_path.exists():
            shutil.rmtree(directory_path)
            logger.info(f"🗑️  Dossier supprimé : {directory_path}")

        return
    except Exception as exc:
        logger.exception("💥 Erreur Smartcut Lite")
        raise CutMindError(
            "❌ Erreur lors du traitement Smartcut Lite.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"directory_path": directory_path}),
        ) from exc
