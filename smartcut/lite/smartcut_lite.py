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

from cutmind.db.repository import CutMindRepository
from cutmind.models_cm.db_models import Video
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from shared.utils.safe_runner import safe_main
from shared.utils.settings import get_settings
from smartcut.lite.load_segments import load_segments_from_directory
from smartcut.lite.relocate_and_rename_segments import relocate_and_rename_segments
from smartcut.services.analyze.apply_confidence import apply_confidence_to_session
from smartcut.services.analyze.ia_pipeline_service import run_ia_pipeline

settings = get_settings()

FRAME_PER_SEGMENT = settings.smartcut.frame_per_segment
AUTO_FRAMES = settings.smartcut.auto_frames
FPS_EXTRACT = settings.analyse_segment.fps_extract
BASE_RATE = settings.analyse_segment.base_rate


@safe_main
@with_child_logger
def lite_cut(directory_path: Path, logger: LoggerProtocol | None = None) -> None:
    """
    Pipeline simplifié SmartCut pour segments déjà coupés.
    Args:
        directory_path: Dossier contenant les segments vidéo (.mp4/.mkv)
    """
    logger = ensure_logger(logger, __name__)
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
                status="init",
                origin="smartcut_lite",
            )
        repo.insert_video_with_segments(new_vid)
        vid = repo.get_video_with_segments(video_uid=new_vid.uid)

        if not vid:
            raise Exception("Impossible de créer ou récupérer la vidéo SmartCut-Lite.")

        load_segments_from_directory(vid, directory_path, logger=logger)

        vid.status = "scenes_done"
        repo.update_video(vid)

        vid = repo.get_video_with_segments(video_uid=vid.uid)
        if not vid or not vid.status:
            raise Exception("Impossible de récupérer la vidéo SmartCut-Lite après chargement des segments.")

        logger.info("💾 Session initialisée (%d segments).", len(vid.segments))

        # Étape 1️⃣ — Analyse IA
        logger.info("🧠 Analyse IA des segments...")
        try:
            ia_results = run_ia_pipeline(
                video_path=str(vid.video_path),
                segments=vid.segments,
                frames_per_segment=FRAME_PER_SEGMENT,
                auto_frames=AUTO_FRAMES,
                base_rate=BASE_RATE,
                fps_extract=FPS_EXTRACT,
                lite=True,
                logger=logger,
            )

            vid.status = "ia_done"
            repo.update_video(vid)
            logger.info("✅ Analyse IA terminée.")

        except Exception as exc:
            logger.error("💥 Erreur durant l’analyse IA : %s", exc)
            raise

        # Étape 2️⃣ — Calcul du score de confiance
        logger.info("📊 Calcul des scores de confiance...")
        apply_confidence_to_session(
            session=vid,
            video_or_dir_name=vid.name,
            model_name=settings.analyse_confidence.model_confidence,
            logger=logger,
        )

        logger.info("✅ Scores de confiance calculés pour %d segments.", len(vid.segments))

        # Étape 3️⃣ — Finalisation
        logger.info("📊 Déplacement des fichiers")
        relocate_and_rename_segments(session=session, logger=logger)
        logger.info("🏁 SmartCut-Lite terminé pour %s", directory_path)
        logger.info("🧾 JSON généré : %s", state_path)
    else:
        logger.debug(f"🧹 Le dossier {directory_path} est vide.")

    if directory_path.exists():
        shutil.rmtree(directory_path)
        logger.info(f"🗑️  Dossier supprimé : {directory_path}")

    return
