"""
video_orchestrator.py (v3.1)
=============================

Nouvelle version avec intégration complète de CutMind :
- SmartCut (complet ou lite)
- Import automatique dans CutMind
- RouterWorker (analyse segments non conformes depuis la base)
"""

import argparse
from datetime import datetime
import gc
from pathlib import Path
import random
import time

import torch

from cutmind.db.repository import CutMindRepository
from cutmind.imports.import_segments_from_csv import import_segments
from cutmind.imports.importer import import_all_smartcut_jsons
from cutmind.process.router_worker import RouterWorker
from shared.models.config_manager import CONFIG
from shared.utils.config import CM_NB_VID_ROUTER, IMPORT_DIR_SC, OUPUT_DIR_SC
from shared.utils.logger import get_logger
from smartcut.lite.smartcut_lite import lite_cut
from smartcut.models_sc.smartcut_model import SmartCutSession
from smartcut.smartcut import multi_stage_cut

logger = get_logger("Smartcut Comfyui Router Orchestrator")

# ============================================================
# ⚙️ Paramètres globaux
# ============================================================
SMARTCUT_BATCH = int(CONFIG.smartcut["smartcut"]["batch_size"])
SCAN_INTERVAL = int(CONFIG.smartcut["smartcut"]["scan_interval"])
USE_CUDA = CONFIG.smartcut["smartcut"]["use_cuda"]


# ============================================================
# 🧹 Outils GPU
# ============================================================
def auto_clean_gpu(max_wait_sec: int = 30) -> None:
    """Nettoie la VRAM GPU et synchronise CUDA."""
    waited = 0
    while not torch.cuda.is_available():
        if waited >= max_wait_sec:
            logger.warning(f"❌ GPU non détecté après {max_wait_sec}s.")
            return
        logger.info("⏳ En attente du GPU CUDA...")
        time.sleep(2)
        waited += 2

    try:
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
        gc.collect()
        free, total = torch.cuda.mem_get_info()
        logger.info(f"🧹 GPU nettoyé : {free / 1e9:.2f} Go libres / {total / 1e9:.2f} Go totaux")
    except Exception as e:
        logger.warning(f"⚠️ Nettoyage VRAM échoué : {e}")


# ============================================================
# 📦 Traitement SmartCut complet
# ============================================================
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

        # 🔹 Import automatique dans CutMind
        logger.info("📥 Import SmartCut JSONs vers CutMind...")
        import_all_smartcut_jsons()

        # 🔹 Import CSV automatique dans CutMind
        logger.info("📥 Import SmartCut CSVs vers CutMind...")
        import_segments()

    except Exception as exc:
        logger.error(f"💥 Erreur SmartCut {video_path.name} : {exc}")
        auto_clean_gpu()


def process_smartcut_folder(folder_path: Path) -> None:
    """Flow SmartCut Lite (segments déjà présents dans un dossier)."""
    try:
        logger.info(f"🚀 SmartCut Lite : dossier {folder_path.name}")
        lite_cut(directory_path=folder_path)

        # 🔹 Import automatique dans CutMind
        logger.info("📥 Import SmartCut JSONs vers CutMind...")
        import_all_smartcut_jsons()

        # 🔹 Import CSV automatique dans CutMind
        logger.info("📥 Import SmartCut CSVs vers CutMind...")
        import_segments()

    except Exception as exc:
        logger.error(f"💥 Erreur SmartCut Lite {folder_path.name} : {exc}")
        auto_clean_gpu()


# ============================================================
# 🔁 Traitement par lot SmartCut
# ============================================================
def list_videos_and_dirs(directory: Path) -> tuple[list[Path], list[Path]]:
    video_exts = (".mp4", ".mov", ".mkv", ".avi", ".wmv")
    videos = [p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in video_exts]
    dirs = [p for p in directory.iterdir() if p.is_dir()]
    return videos, dirs


def process_smartcut_batch(videos: list[Path], dirs: list[Path], max_items: int) -> int:
    """Traite un lot limité de vidéos/dossiers SmartCut. Retourne le nombre total traités."""
    count = 0
    for video_path in videos:
        process_smartcut_video(video_path)
        count += 1
        if count >= max_items:
            return count
    for folder_path in dirs:
        process_smartcut_folder(folder_path)
        count += 1
        if count >= max_items:
            return count
    return count


# ============================================================
# 🎬 Orchestrateur principal
# ============================================================

# 🎨 ANSI Colors
COLOR_RESET = "\033[0m"
COLOR_BLUE = "\033[94m"
COLOR_GREEN = "\033[92m"
COLOR_YELLOW = "\033[93m"
COLOR_RED = "\033[91m"
COLOR_PURPLE = "\033[95m"
COLOR_CYAN = "\033[96m"


def orchestrate(priority: str = "smartcut") -> None:
    """
    Orchestrateur intelligent SmartCut / Router.
    - Sélection aléatoire pondérée selon ratio défini dans le YAML.
    - Plage horaire silencieuse : Router désactivé pendant certaines heures.
    - Logs colorés + affichage du mode courant (auto/forcé).
    """
    logger.info(f"{COLOR_CYAN}🎬 Orchestrateur SmartCut + CutMind démarré.{COLOR_RESET}")
    IMPORT_DIR_SC.mkdir(parents=True, exist_ok=True)

    ratio_smartcut = CONFIG.comfyui_router["orchestrator"].get("ratio_smartcut", 0.7)
    forbidden_hours = CONFIG.comfyui_router["orchestrator"].get("router_forbidden_hours", [])
    scan_interval = CONFIG.comfyui_router["processor"].get("scan_interval", 60)

    cycle = 0
    total_smartcut = 0
    total_router = 0

    # Détermination du mode au démarrage
    if ratio_smartcut >= 1.0:
        mode_label = f"{COLOR_GREEN}⚙️ Mode forcé: SmartCut uniquement{COLOR_RESET}"
    elif ratio_smartcut <= 0.0:
        mode_label = f"{COLOR_YELLOW}⚙️ Mode forcé: Router uniquement{COLOR_RESET}"
    else:
        mode_label = f"{COLOR_CYAN}⚙️ Mode auto: ratio_smartcut={ratio_smartcut:.2f}{COLOR_RESET}"

    logger.info(mode_label)

    while True:
        try:
            cycle += 1
            logger.info(f"{COLOR_PURPLE}\n🔁 === Cycle {cycle} démarré ==={COLOR_RESET}")

            smartcut_videos, smartcut_dirs = list_videos_and_dirs(IMPORT_DIR_SC)
            smartcut_pending = len(smartcut_videos) + len(smartcut_dirs)

            repo = CutMindRepository()
            router_pending = len(repo.get_nonstandard_videos(limit_videos=CM_NB_VID_ROUTER))

            logger.info(f"📦 SmartCut: {smartcut_pending} | Router: {router_pending}")

            batch_smartcut = 0
            batch_router = 0

            # --- DÉCISION INTELLIGENTE ---
            current_hour = datetime.now().hour
            router_allowed = current_hour not in forbidden_hours
            choice_value = random.random()

            pick_smartcut = (choice_value <= ratio_smartcut) or not router_allowed or router_pending == 0

            # --- SMARTCUT ---
            if pick_smartcut and smartcut_pending > 0:
                logger.info(
                    f"{COLOR_GREEN}🎲 Choix: SmartCut (valeur={choice_value:.2f}, ratio={ratio_smartcut}){COLOR_RESET}"
                )
                logger.info(
                    f"{COLOR_BLUE}🚀 Lancement SmartCut sur {min(smartcut_pending, SMARTCUT_BATCH)} \
                        éléments{COLOR_RESET}"
                )
                batch_smartcut = process_smartcut_batch(smartcut_videos, smartcut_dirs, SMARTCUT_BATCH)
                total_smartcut += batch_smartcut

            # --- ROUTER ---
            elif router_allowed and router_pending > 0:
                logger.info(
                    f"{COLOR_YELLOW}🎲 Choix: Router (valeur={choice_value:.2f}, ratio={ratio_smartcut}){COLOR_RESET}"
                )
                logger.info(
                    f"{COLOR_BLUE}🚀 Lancement RouterWorker ({router_pending} vidéos non conformes){COLOR_RESET}"
                )
                worker = RouterWorker(limit_videos=CM_NB_VID_ROUTER)
                worker.run()
                batch_router = router_pending
                total_router += batch_router

            # --- ROUTER BLOQUÉ (NUIT) ---
            elif not router_allowed:
                logger.info(f"{COLOR_RED}🌙 Plage horaire silencieuse — Router désactivé (SmartCut forcé){COLOR_RESET}")
                if smartcut_pending > 0:
                    batch_smartcut = process_smartcut_batch(smartcut_videos, smartcut_dirs, SMARTCUT_BATCH)
                    total_smartcut += batch_smartcut

            # --- AUCUNE TÂCHE ---
            else:
                logger.info(f"{COLOR_CYAN}📂 Rien à traiter — pause 60s.{COLOR_RESET}")
                time.sleep(60)

            logger.info(
                f"✅ Fin cycle {cycle} — "
                f"SmartCut:{batch_smartcut} | Router:{batch_router} "
                f"(Total SmartCut:{total_smartcut} | Total Router:{total_router})"
            )
            logger.info(f"⏳ Pause {scan_interval}s avant le prochain scan.")
            time.sleep(scan_interval)

        except Exception as err:
            logger.exception(f"{COLOR_RED}💥 Erreur inattendue orchestrateur : {err}{COLOR_RESET}")
            time.sleep(30)


# ============================================================
# 🚀 CLI
# ============================================================
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Orchestrateur SmartCut + CutMind Router")
    parser.add_argument(
        "--priority",
        choices=["smartcut", "router"],
        default="smartcut",
        help="Source prioritaire (défaut: smartcut)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    orchestrate(priority=args.priority)
