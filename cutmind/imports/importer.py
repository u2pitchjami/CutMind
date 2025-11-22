"""
Importeur principal des sessions SmartCut (v3.2)
================================================

- Scanne les JSON SmartCut (standard ou lite)
- Valide et typage via Pydantic
- Convertit en objet Video complet via convert_json_to_video()
- Insère dans la base via CutMindRepository
- Exécute la validation automatique
- Déplace le JSON vers validated/ ou manual_review/

Exécution :
    python importer.py
    python importer.py --dry-run
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil

from cutmind.db.repository import CutMindRepository
from cutmind.models_cm.smartcut_parser import convert_json_to_video, parse_smartcut_json
from cutmind.validation.main_validation import validation
from shared.utils.config import JSON_IMPORTED, JSON_STATES
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger


# =====================================================================
# ⚙️ Fonction principale
# =====================================================================
@with_child_logger
def import_all_smartcut_jsons(
    state_dir: Path = Path(JSON_STATES),
    imported_dir: Path = Path(JSON_IMPORTED),
    dry_run: bool = False,
    logger: LoggerProtocol | None = None,
) -> None:
    """
    Parcourt tous les fichiers SmartCut JSON dans `state_dir`,
    les importe en base via CutMindRepository et applique une
    validation automatique post-insertion.
    """
    logger = ensure_logger(logger, __name__)
    logger.info("🚀 Démarrage de l'import SmartCut depuis %s", state_dir)
    repo = CutMindRepository()

    if not state_dir.exists():
        logger.error("❌ Dossier inexistant : %s", state_dir)
        return

    imported_dir.mkdir(parents=True, exist_ok=True)

    json_files = sorted(state_dir.glob("*.smartcut_state.json"))
    logger.info("🔍 %d fichiers SmartCut détectés dans %s", len(json_files), state_dir)

    imported_count = 0
    skipped_count = 0
    error_count = 0

    for json_path in json_files:
        try:
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)

            # --- Validation et typage ---
            ok, session, session_type, reason = parse_smartcut_json(data, json_path.name, logger=logger)
            if not ok:
                logger.warning("⏭️ Ignoré (%s): %s", reason, json_path.name)
                skipped_count += 1
                continue

            # --- Doublon ---
            if repo.video_exists(session.uid, logger=logger):
                logger.info("♻️ Vidéo déjà en base : %s", session.uid)
                skipped_count += 1
                continue

            # --- Conversion en objet Video complet ---
            video = convert_json_to_video(session)

            if dry_run:
                logger.info("🧪 (dry-run) Importerait : %s (%s)", json_path.name, session_type)
                skipped_count += 1
                continue

            # --- Insertion ---
            video_id = repo.insert_video_with_segments(video, logger=logger)
            logger.debug("✅ Insertion DB réussie pour %s (id=%d)", video.uid, video_id)

            shutil.move(json_path, imported_dir)
            imported_count += 1

        except Exception as exc:  # pylint: disable=broad-except
            logger.error("❌ Erreur import %s : %s", json_path.name, exc, exc_info=True)
            error_count += 1

    # --- Résumé final ---
    logger.info(
        "🏁 Import terminé — %d ajoutés, %d ignorés, %d erreurs",
        imported_count,
        skipped_count,
        error_count,
    )
    validation(logger=logger)
