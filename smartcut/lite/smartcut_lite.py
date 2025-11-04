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

from shared.models.config_manager import CONFIG
from shared.utils.config import JSON_STATES_DIR_SC
from shared.utils.logger import get_logger
from shared.utils.safe_runner import safe_main
from smartcut.analyze.analyze_confidence import compute_confidence
from smartcut.analyze.main_analyze import analyze_video_segments
from smartcut.lite.relocate_and_rename_segments import relocate_and_rename_segments
from smartcut.models_sc.lite_session import SmartCutLiteSession

logger = get_logger(__name__)

FRAME_PER_SEGMENT = CONFIG.smartcut["smartcut"]["frame_per_segment"]
AUTO_FRAMES = CONFIG.smartcut["smartcut"]["auto_frames"]


@safe_main
def lite_cut(directory_path: Path) -> None:
    """
    Pipeline simplifié SmartCut pour segments déjà coupés.
    Args:
        directory_path: Dossier contenant les segments vidéo (.mp4/.mkv)
    """
    logger.info("🚀 Démarrage SmartCut-Lite sur : %s", directory_path)
    if any(directory_path.iterdir()):
        # Étape 0️⃣ — Initialisation session
        session = SmartCutLiteSession(directory_path)
        session.load_segments_from_directory()
        session.status = "scenes_done"

        state_path = JSON_STATES_DIR_SC / f"{session.dir_path.name}.smartcut_state.json"
        session.enrich_segments_metadata()
        session.save(str(state_path))
        logger.info("💾 Session initialisée (%d segments).", len(session.segments))

        # Étape 1️⃣ — Analyse IA
        logger.info("🧠 Analyse IA des segments...")
        try:
            analyze_video_segments(
                video_path=session.dir_path.name,
                frames_per_segment=FRAME_PER_SEGMENT,
                auto_frames=AUTO_FRAMES,
                session=session,
                lite=True,
            )
            session.status = "ia_done"
            session.save(str(state_path))
            logger.info("✅ Analyse IA terminée.")

        except Exception as exc:
            logger.error("💥 Erreur durant l’analyse IA : %s", exc)
            session.errors.append(str(exc))
            session.save(str(state_path))
            raise

        # Étape 2️⃣ — Calcul du score de confiance
        logger.info("📊 Calcul des scores de confiance...")
        for seg in session.segments:
            if seg.ai_status == "done":
                seg.confidence = compute_confidence(seg.description, seg.keywords)
                session.save(str(state_path))
        session.status = "confidence_done"
        session.save(str(state_path))
        logger.info("✅ Scores de confiance calculés pour %d segments.", len(session.segments))

        # Étape 3️⃣ — Finalisation
        logger.info("📊 Déplacement des fichiers")
        relocate_and_rename_segments(session=session)
        logger.info("🏁 SmartCut-Lite terminé pour %s", directory_path)
        logger.info("🧾 JSON généré : %s", state_path)
    else:
        logger.debug(f"🧹 Le dossier {directory_path} est vide.")

    if directory_path.exists():
        shutil.rmtree(directory_path)
        logger.info(f"🗑️  Dossier supprimé : {directory_path}")

    return
