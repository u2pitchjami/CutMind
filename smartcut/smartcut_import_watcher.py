"""
smartcut_import_watcher.py
==========================

Surveille un dossier d'import et lance le traitement SmartCut pour chaque vidéo :
- Crée ou reprend automatiquement la session SmartCut
- Saute les vidéos déjà terminées (status="cut")
- Gère les erreurs et les relances automatiques

Peut être exécuté manuellement, via cron, ou comme service Docker.
"""

from __future__ import annotations

import gc
from pathlib import Path
import time

import torch

from shared.models.config_manager import CONFIG
from shared.models.smartcut_model import SmartCutSession
from shared.utils.config import IMPORT_DIR_SC, JSON_STATES_DIR_SC, OUPUT_DIR_SC
from shared.utils.logger import get_logger
from smartcut.smartcut import multi_stage_cut

SCAN_INTERVAL = CONFIG.smartcut["smartcut"]["scan_interval"]  # secondes entre deux scans
USE_CUDA = CONFIG.smartcut["smartcut"]["use_cuda"]

# --- Initialisation logger ---

logger = get_logger("smartcut_watcher")


# --- Nettoyage automatique GPU au démarrage ---
def auto_clean_gpu(max_wait_sec: int = 120) -> None:
    """
    Attente et nettoyage de la VRAM GPU si disponible.
    """
    waited = 0
    while not torch.cuda.is_available():
        if waited >= max_wait_sec:
            print(f"❌ GPU non détecté après {max_wait_sec}s. Abandon.")
            raise RuntimeError("CUDA device not available.")
        print("⏳ En attente du GPU CUDA...")
        time.sleep(2)
        waited += 2

    try:
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
        gc.collect()
        free, total = torch.cuda.mem_get_info()
        print(f"🧹 GPU auto-clean: VRAM libre {free / 1e9:.2f} Go / {total / 1e9:.2f} Go")
    except Exception as e:
        print(f"⚠️ Nettoyage VRAM échoué : {e}")


auto_clean_gpu()


def list_videos(directory: Path) -> list[Path]:
    """
    Retourne la liste des vidéos valides dans un dossier.
    """
    exts = (".mp4", ".mov", ".mkv", ".avi", ".wmv")
    return [p for p in directory.glob("*") if p.suffix.lower() in exts]


def process_video(video_path: Path) -> None:
    """
    Traite une seule vidéo (création/reprise de session).
    """
    try:
        state_path = JSON_STATES_DIR_SC / f"{video_path.stem}.smartcut_state.json"
        session = SmartCutSession.load(str(state_path))

        if session:
            logger.info(f"♻️ Reprise session {video_path.name} → status : {session.status}")
        else:
            logger.info(f"✨ Nouvelle vidéo détectée : {video_path.name}")
            session = SmartCutSession(video=str(video_path), duration=0.0, fps=0.0)
            session.save(str(state_path))

        # Skip si déjà terminée
        if session.status == "cut":
            logger.info(f"✅ {video_path.name} déjà terminée, skip.")
            return

        # Lancer ou reprendre le traitement
        logger.info(f"🚀 Lancement du flow SmartCut pour {video_path.name}")
        multi_stage_cut(video_path=video_path, out_dir=OUPUT_DIR_SC, use_cuda=USE_CUDA)

    except Exception as exc:  # pylint: disable=broad-except
        logger.error(f"💥 Erreur lors du traitement de {video_path.name} : {exc}")
        auto_clean_gpu()


def main() -> None:
    """
    Boucle principale du watcher.
    """
    logger.info("🎬 Démarrage du SmartCut Import Watcher...")
    IMPORT_DIR_SC.mkdir(parents=True, exist_ok=True)
    OUPUT_DIR_SC.mkdir(parents=True, exist_ok=True)

    while True:
        videos = list_videos(IMPORT_DIR_SC)
        if not videos:
            logger.info("📂 Aucun fichier vidéo détecté. Nouvelle vérification dans 60s...")
        else:
            logger.info(f"🔍 {len(videos)} vidéos détectées dans {IMPORT_DIR_SC}")
            for video_path in videos:
                process_video(video_path)
        logger.info(f"⏳ Attente {SCAN_INTERVAL}s avant le prochain scan.")
        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    # Vérifie tout au démarrage
    try:
        CONFIG.validate()
    except ValueError as e:
        print(f"Erreur de config : {e}")
        exit(1)
    try:
        auto_clean_gpu()
    except RuntimeError as e:
        logger.error(f"Erreur CUDA : {e}")
        time.sleep(10)  # anti-boucle infernale
        exit(1)
    main()
