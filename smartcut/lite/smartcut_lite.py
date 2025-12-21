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
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.config import ERROR_DIR_SC
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from shared.utils.safe_runner import safe_main
from shared.utils.settings import get_settings
from smartcut.executors.analyze.split_utils import move_to_error
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
                    status="init",
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

            # Étape 1️⃣ — Analyse IA
            if vid.status in ("scenes_done",):
                logger.info("🧠 Analyse IA des segments...")
                pending_segments = vid.get_pending_segments()
                logger.debug("Segments en attente : %s", [s.id for s in pending_segments])

                if not pending_segments:
                    logger.info("✅ Tous les segments ont déjà été traités par l’IA.")
                    vid.status = "ia_done"
                    repo.update_video(vid)
                else:
                    logger.info("📊 %d segments à traiter par l’IA...", len(pending_segments))
                try:
                    run_ia_pipeline(
                        video_path=str(vid.video_path),
                        segments=pending_segments,
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
                    if vid.tags == "" or "ia_error" not in vid.tags:
                        vid.add_tag_vid("ia_error")
                    else:
                        error_path = move_to_error(file_path=Path(str(vid.video_path)), error_root=ERROR_DIR_SC)
                        vid.video_path = str(error_path)
                        vid.status = "error"
                        logger.info(f"🗑️ Fichier déplacé vers le dossier Error : {error_path}")
                    repo.update_video(vid)
                    raise CutMindError(
                        f"❌ Erreur lors de l'analyse IA {vid.name}",
                        code=ErrCode.UNEXPECTED,
                    ) from exc
            else:
                logger.info("⏩ Étape IA déjà effectuée — skip.")

            # Étape 2️⃣ — Calcul du score de confiance
            if vid.status == "ia_done":
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
                relocate_and_rename_segments(session=vid, logger=logger)
                vid.status = "smartcut_done"
                repo.update_video(vid)
                logger.info("🏁 SmartCut-Lite terminé pour %s", directory_path)
        else:
            logger.debug(f"🧹 Le dossier {directory_path} est vide.")

        if directory_path.exists():
            shutil.rmtree(directory_path)
            logger.info(f"🗑️  Dossier supprimé : {directory_path}")

        return
    except CutMindError as err:
        raise err.with_context(get_step_ctx({"directory_path": directory_path})) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur lors du traitement Smartcut Lite.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"directory_path": directory_path}),
        ) from exc
