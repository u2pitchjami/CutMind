"""
video_orchestrator.py (v2)
==========================

Orchestre le traitement vidéo entre SmartCut et ComfyUI Router.

- Scanne les deux dossiers d'import (`smartcut` et `router`)
- Si un dossier est trouvé dans SmartCut → SmartCut Lite (segments déjà découpés)
- Si une vidéo est trouvée → SmartCut complet
"""

import argparse
import gc
from pathlib import Path
import time

import torch

from comfyui_router.models_cr.processor import VideoProcessor
from shared.models.config_manager import CONFIG
from shared.utils.config import IMPORT_DIR_SC, INPUT_DIR, OUPUT_DIR_SC, OUTPUT_DIR
from shared.utils.logger import get_logger
from shared.utils.trash import delete_files
from shared.utils.wait_for_comfyui import wait_for_comfyui
from smartcut.lite.smartcut_lite import lite_cut
from smartcut.models_sc.smartcut_model import SmartCutSession
from smartcut.smartcut import multi_stage_cut

logger = get_logger("Smartcut Comfyui Router")

SCAN_INTERVAL = CONFIG.smartcut["smartcut"]["scan_interval"]
USE_CUDA = CONFIG.smartcut["smartcut"]["use_cuda"]


def auto_clean_gpu(max_wait_sec: int = 30) -> None:
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


def list_videos_and_dirs(directory: Path) -> tuple[list[Path], list[Path]]:
    """Retourne les vidéos ET les dossiers à la racine du répertoire (pas récursif)."""
    video_exts = (".mp4", ".mov", ".mkv", ".avi", ".wmv")

    videos = [p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in video_exts]
    dirs = [p for p in directory.iterdir() if p.is_dir()]

    return videos, dirs


def process_smartcut_video(video_path: Path) -> None:
    """Flow SmartCut complet (vidéo non découpée)."""
    try:
        state_path = OUPUT_DIR_SC / f"{video_path.stem}.smartcut_state.json"
        session = SmartCutSession.load(str(state_path))

        if session and session.status == "cut":
            logger.info(f"✅ {video_path.name} déjà traitée par SmartCut.")
            return

        if not session:
            session = SmartCutSession(video=str(video_path), duration=0.0, fps=0.0)
            session.save(str(state_path))

        logger.info(f"🚀 SmartCut (complet) : {video_path.name}")
        multi_stage_cut(video_path=video_path, out_dir=OUPUT_DIR_SC, use_cuda=USE_CUDA)

    except Exception as exc:
        logger.error(f"💥 Erreur SmartCut {video_path.name} : {exc}")
        auto_clean_gpu()


def process_smartcut_folder(folder_path: Path) -> None:
    """Flow SmartCut Lite (segments déjà présents dans un dossier)."""
    try:
        logger.info(f"🚀 SmartCut Lite : dossier {folder_path.name}")
        lite_cut(directory_path=folder_path)
    except Exception as exc:
        logger.error(f"💥 Erreur SmartCut Lite {folder_path.name} : {exc}")
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
        router_videos = [p for p in INPUT_DIR.glob("*") if p.is_file()]
        smartcut_videos, smartcut_dirs = list_videos_and_dirs(IMPORT_DIR_SC)

        source = None
        if priority == "router":
            source = "router" if router_videos else "smartcut" if (smartcut_videos or smartcut_dirs) else None
        elif priority == "smartcut":
            source = "smartcut" if (smartcut_videos or smartcut_dirs) else "router" if router_videos else None
        elif priority == "auto":
            source = "router" if router_videos else "smartcut" if (smartcut_videos or smartcut_dirs) else None

        if not source:
            logger.info("📂 Aucun fichier détecté. Nouvelle vérification dans 60s...")
        else:
            logger.info(f"🔍 Traitement depuis dossier : {source}")
            if source == "router":
                for video_path in router_videos:
                    process_router_video(video_path)
            else:
                # ⚙️ Traitement SmartCut : vidéo ou dossier
                for video_path in smartcut_videos:
                    process_smartcut_video(video_path)
                for folder_path in smartcut_dirs:
                    process_smartcut_folder(folder_path)

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
        time.sleep(10)
        exit(1)
    orchestrate(priority=args.priority)
