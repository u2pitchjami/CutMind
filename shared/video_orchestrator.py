"""
video_orchestrator.py
======================

Orchestre le traitement vidéo entre SmartCut et ComfyUI Router.

- Scan les deux dossiers d'import (`smartcut` et `router`)
- Priorise automatiquement ou via l'argument --priority
- Lance le traitement approprié pour chaque vidéo
"""

import argparse
import gc
from pathlib import Path
import time

import torch

from shared.models.config_manager import CONFIG
from shared.models.processor import VideoProcessor
from shared.models.smartcut_model import SmartCutSession
from shared.utils.config import IMPORT_DIR_SC, INPUT_DIR, OUPUT_DIR_SC, OUTPUT_DIR
from shared.utils.logger import get_logger
from shared.utils.trash import delete_files
from shared.utils.wait_for_comfyui import wait_for_comfyui
from smartcut.smartcut import multi_stage_cut

logger = get_logger("Smartcut Comfyui Router")

SCAN_INTERVAL = CONFIG.smartcut["smartcut"]["scan_interval"]
USE_CUDA = CONFIG.smartcut["smartcut"]["use_cuda"]


def auto_clean_gpu(max_wait_sec: int = 30) -> None:
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


def list_videos(directory: Path) -> list[Path]:
    exts = (".mp4", ".mov", ".mkv", ".avi", ".wmv")
    return [p for p in directory.glob("*") if p.suffix.lower() in exts]


def process_smartcut_video(video_path: Path) -> None:
    try:
        state_path = OUPUT_DIR_SC / f"{video_path.stem}.smartcut_state.json"
        session = SmartCutSession.load(str(state_path))

        if session and session.status == "cut":
            logger.info(f"✅ {video_path.name} déjà traitée par SmartCut.")
            return

        if not session:
            session = SmartCutSession(video=str(video_path), duration=0.0, fps=0.0)
            session.save(str(state_path))

        logger.info(f"🚀 SmartCut: traitement {video_path.name}")
        multi_stage_cut(video_path=video_path, out_dir=OUPUT_DIR_SC, use_cuda=USE_CUDA)

    except Exception as exc:
        logger.error(f"💥 Erreur SmartCut {video_path.name} : {exc}")
        auto_clean_gpu()


def process_router_video(video_path: Path) -> None:
    try:
        processor = VideoProcessor()
        logger.info(f"🚀 Router: traitement {video_path.name}")
        delete_files(path=OUTPUT_DIR, ext="*.png")
        delete_files(path=OUTPUT_DIR, ext="*.mp4")
        processor.process(video_path=video_path, force_deinterlace=False)
    except Exception as exc:
        logger.error(f"💥 Erreur Router {video_path.name} : {exc}")
        auto_clean_gpu()


def orchestrate(priority: str = "router") -> None:
    logger.info("🎬 Orchestrateur démarré.")
    IMPORT_DIR_SC.mkdir(parents=True, exist_ok=True)
    INPUT_DIR.mkdir(parents=True, exist_ok=True)

    while True:
        router_videos = list_videos(INPUT_DIR)
        smartcut_videos = list_videos(IMPORT_DIR_SC)

        source = None
        if priority == "router":
            source = "router" if router_videos else "smartcut" if smartcut_videos else None
        elif priority == "smartcut":
            source = "smartcut" if smartcut_videos else "router" if router_videos else None
        elif priority == "auto":
            source = "router" if router_videos else "smartcut" if smartcut_videos else None

        if not source:
            logger.info("📂 Aucun fichier détecté. Nouvelle vérification dans 60s...")
        else:
            logger.info(f"🔍 Traitement depuis dossier : {source}")
            if source == "router":
                for video_path in router_videos:
                    process_router_video(video_path)
            else:
                for video_path in smartcut_videos:
                    process_smartcut_video(video_path)

        logger.info(f"⏳ Attente {SCAN_INTERVAL}s avant le prochain scan.")
        time.sleep(SCAN_INTERVAL)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Orchestrateur SmartCut + ComfyUI Router")
    parser.add_argument(
        "--priority", choices=["router", "smartcut", "auto"], default="auto", help="Source prioritaire (défaut: auto)"
    )
    return parser.parse_args()


if __name__ == "__main__":
    try:
        wait_for_comfyui()
        CONFIG.validate()
    except ValueError as e:
        print(f"Erreur de config : {e}")
        exit(1)

    args = parse_args()
    try:
        auto_clean_gpu()
    except RuntimeError as e:
        logger.error(f"Erreur CUDA : {e}")
        time.sleep(10)  # anti-boucle infernale
        exit(1)
    orchestrate(priority=args.priority)
