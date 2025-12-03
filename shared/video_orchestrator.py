"""
video_orchestrator.py (v3.1)
=============================

Nouvelle version avec intégration complète de CutMind :
- SmartCut (complet ou lite)
- Import automatique dans CutMind
- RouterWorker (analyse segments non conformes depuis la base)
"""

from datetime import datetime
import gc
from pathlib import Path
import random
import time

import torch

from cutmind.check.enhanced import check_enhanced_segments
from cutmind.check.secure_in_router import check_secure_in_router
from cutmind.db.repository import CutMindRepository
from cutmind.process.already_enhanced import process_standard_videos
from cutmind.process.router_worker import RouterWorker
from cutmind.services.manual.update_from_csv import update_segments_csv
from cutmind.validation.main_validation import validation
from shared.models.config_manager import reload_and_apply
from shared.utils.config import (
    CM_NB_VID_ROUTER,
    COLOR_BLUE,
    COLOR_CYAN,
    COLOR_GREEN,
    COLOR_PURPLE,
    COLOR_RED,
    COLOR_RESET,
    COLOR_YELLOW,
    IMPORT_DIR_SC,
    OUTPUT_DIR_SC,
)
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from shared.utils.settings import get_settings
from smartcut.lite.smartcut_lite import lite_cut
from smartcut.smartcut import multi_stage_cut

settings = get_settings()

SMARTCUT_BATCH = settings.smartcut.batch_size
SCAN_INTERVAL = settings.smartcut.scan_interval
USE_CUDA = settings.smartcut.use_cuda
ratio_smartcut = settings.router_orchestrator.ratio_smartcut
forbidden_hours = settings.router_orchestrator.forbidden_hours


# ============================================================
# 🧹 Outils GPU
# ============================================================
@with_child_logger
def auto_clean_gpu(max_wait_sec: int = 30, logger: LoggerProtocol | None = None) -> None:
    """Nettoie la VRAM GPU et synchronise CUDA."""
    logger = ensure_logger(logger, __name__)
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
@with_child_logger
def process_smartcut_video(video_path: Path, logger: LoggerProtocol | None = None) -> None:
    logger = ensure_logger(logger, __name__)
    try:
        logger.info(f"🚀 SmartCut (complet) : {video_path.name}")

        multi_stage_cut(video_path=video_path, out_dir=OUTPUT_DIR_SC, use_cuda=USE_CUDA, logger=logger)

    except Exception as exc:
        logger.error(f"💥 Erreur SmartCut {video_path.name} : {exc}")
        auto_clean_gpu(logger=logger)


@with_child_logger
def process_smartcut_folder(folder_path: Path, logger: LoggerProtocol | None = None) -> None:
    """Flow SmartCut Lite (segments déjà présents dans un dossier)."""
    logger = ensure_logger(logger, __name__)
    try:
        logger.info(f"🚀 SmartCut Lite : dossier {folder_path.name}")
        lite_cut(directory_path=folder_path, logger=logger)

    except Exception as exc:
        logger.error(f"💥 Erreur SmartCut Lite {folder_path.name} : {exc}")
        auto_clean_gpu(logger=logger)


# ============================================================
# 🔁 Traitement par lot SmartCut
# ============================================================
def list_videos_and_dirs(directory: Path) -> tuple[list[Path], list[Path]]:
    video_exts = (".mp4", ".mov", ".mkv", ".avi", ".wmv")
    videos = [p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in video_exts]
    dirs = [p for p in directory.iterdir() if p.is_dir()]
    return videos, dirs


@with_child_logger
def process_smartcut_batch(
    videos: list[Path], dirs: list[Path], max_items: int, logger: LoggerProtocol | None = None
) -> int:
    """Traite un lot limité de vidéos/dossiers SmartCut. Retourne le nombre total traités."""
    logger = ensure_logger(logger, __name__)
    count = 0
    for video_path in videos:
        process_smartcut_video(video_path, logger=logger)
        count += 1
        if count >= max_items:
            return count
    for folder_path in dirs:
        process_smartcut_folder(folder_path, logger=logger)
        count += 1
        if count >= max_items:
            return count
    return count


# ============================================================
# 🎬 Orchestrateur principal
# ============================================================
@with_child_logger
def orchestrate(priority: str = "smartcut", logger: LoggerProtocol | None = None) -> None:
    """
    Orchestrateur intelligent SmartCut / Router.
    - Sélection aléatoire pondérée selon ratio défini dans le YAML.
    - Plage horaire silencieuse : Router désactivé pendant certaines heures.
    - Logs colorés + affichage du mode courant (auto/forcé).
    """
    logger = ensure_logger(logger, __name__)
    logger.info(f"{COLOR_CYAN}🎬 Orchestrateur SmartCut + CutMind démarré.{COLOR_RESET}")
    IMPORT_DIR_SC.mkdir(parents=True, exist_ok=True)

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
    check_secure_in_router(logger=logger)
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
                batch_smartcut = process_smartcut_batch(smartcut_videos, smartcut_dirs, SMARTCUT_BATCH, logger=logger)
                total_smartcut += batch_smartcut

            # --- ROUTER ---
            elif router_allowed and router_pending > 0:
                logger.info(
                    f"{COLOR_YELLOW}🎲 Choix: Router (valeur={choice_value:.2f}, ratio={ratio_smartcut}){COLOR_RESET}"
                )
                logger.info(
                    f"{COLOR_BLUE}🚀 Lancement RouterWorker ({router_pending} vidéos non conformes){COLOR_RESET}"
                )
                worker = RouterWorker(limit_videos=CM_NB_VID_ROUTER, logger=logger)
                worker.run(logger=logger)
                batch_router = router_pending
                total_router += batch_router

            # --- ROUTER BLOQUÉ (NUIT) ---
            elif not router_allowed:
                logger.info(f"{COLOR_RED}🌙 Plage horaire silencieuse — Router désactivé (SmartCut forcé){COLOR_RESET}")
                if smartcut_pending > 0:
                    batch_smartcut = process_smartcut_batch(
                        smartcut_videos, smartcut_dirs, SMARTCUT_BATCH, logger=logger
                    )
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
            logger.info(f"⏳ Pause {SCAN_INTERVAL}s avant le prochain scan.")
            reload_and_apply(logger=logger)
            time.sleep(SCAN_INTERVAL)
            validation()

            # 🔹 Import CSV automatique dans CutMind
            logger.info("📥 Import SmartCut CSVs vers CutMind...")
            update_segments_csv(logger=logger)
            check_enhanced_segments(max_videos=1, logger=logger)
            process_standard_videos(limit=1, logger=logger)

        except Exception as err:
            logger.exception(f"{COLOR_RED}💥 Erreur inattendue orchestrateur : {err}{COLOR_RESET}")
            time.sleep(30)
