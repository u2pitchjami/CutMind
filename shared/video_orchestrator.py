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

from cutmind.check_script import main_check_script
from cutmind.db.repository import CutMindRepository
from cutmind.process.router_worker import RouterWorker
from cutmind.services.check.secure_in_router import check_secure_in_router
from cutmind.services.main_validation import validation
from cutmind.services.manual.update_from_csv import update_segments_csv
from shared.models.config_manager import reload_and_apply
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
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
from shared.utils.logger import LoggerProtocol, ensure_logger, get_logger, with_child_logger
from shared.utils.settings import get_settings
from smartcut.lite.smartcut_lite import lite_cut
from smartcut.smartcut import multi_stage_cut

settings = get_settings()

SMARTCUT_BATCH = settings.smartcut.batch_size
SCAN_INTERVAL = settings.smartcut.scan_interval
USE_CUDA = settings.smartcut.use_cuda
ratio_smartcut = settings.router_orchestrator.ratio_smartcut
forbidden_hours = settings.router_orchestrator.forbidden_hours
start_audit = settings.cutmind_audit.start
end_audit = settings.cutmind_audit.end


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
    except CutMindError as err:
        raise err.with_context(get_step_ctx()) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur lors du Nettoyage VRAM.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx(),
        ) from exc


# ============================================================
# 📦 Traitement SmartCut complet
# ============================================================
def process_smartcut_video(video_path: Path) -> None:
    logger = get_logger("CutMind-SmartCut")
    try:
        logger.info(f"🚀 SmartCut (complet) : {video_path.name}")

        multi_stage_cut(video_path=video_path, out_dir=OUTPUT_DIR_SC, use_cuda=USE_CUDA, logger=logger)

    except CutMindError as err:
        auto_clean_gpu(logger=logger)
        raise err.with_context(get_step_ctx({"video_path.name": video_path.name})) from err
    except Exception as exc:
        auto_clean_gpu(logger=logger)
        raise CutMindError(
            "❌ Erreur lors du process Smartcut.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video_path.name": video_path.name}),
        ) from exc


def process_smartcut_folder(folder_path: Path) -> None:
    """Flow SmartCut Lite (segments déjà présents dans un dossier)."""
    logger = get_logger("CutMind-SmartCutLite")
    try:
        logger.info(f"🚀 SmartCut Lite : dossier {folder_path.name}")
        lite_cut(directory_path=folder_path)

    except CutMindError as err:
        auto_clean_gpu(logger=logger)
        raise err.with_context(get_step_ctx({"folder_path.name": folder_path.name})) from err
    except Exception as exc:
        auto_clean_gpu(logger=logger)
        raise CutMindError(
            "❌ Erreur lors du process Smartcut Lite.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"folder_path.name": folder_path.name}),
        ) from exc


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
    try:
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
    except CutMindError as err:
        auto_clean_gpu(logger=logger)
        raise err.with_context(get_step_ctx()) from err
    except Exception as exc:
        auto_clean_gpu(logger=logger)
        raise CutMindError(
            "❌ Erreur lors du process Smartcut batch.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx(),
        ) from exc


def is_in_audit_window(start_str: str, end_str: str) -> bool:
    now = datetime.now().time()
    start = datetime.strptime(start_str, "%H:%M").time()
    end = datetime.strptime(end_str, "%H:%M").time()

    if start <= end:
        # Ex : 00:00 à 00:15, ou 08:00 à 12:00
        return start <= now <= end
    else:
        # Ex : 23:00 à 01:00 → traverse minuit
        return now >= start or now <= end


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
    try:
        check_secure_in_router(logger=logger)
    except CutMindError as exc:
        logger.exception("[%s] %s | ctx=%r", exc.code, str(exc), exc.ctx)
    while True:
        try:
            cycle += 1
            logger.info(f"{COLOR_PURPLE}\n🔁 === Cycle {cycle} démarré ==={COLOR_RESET}")

            smartcut_videos, smartcut_dirs = list_videos_and_dirs(IMPORT_DIR_SC)
            smartcut_pending = len(smartcut_videos) + len(smartcut_dirs)

            repo = CutMindRepository()
            try:
                router_pending = len(repo.get_nonstandard_videos(limit_videos=CM_NB_VID_ROUTER))
            except CutMindError as exc:
                logger.exception("[%s] %s | ctx=%r", exc.code, str(exc), exc.ctx)

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
                try:
                    batch_smartcut = process_smartcut_batch(
                        smartcut_videos, smartcut_dirs, SMARTCUT_BATCH, logger=logger
                    )
                except CutMindError as exc:
                    logger.exception("[%s] %s | ctx=%r", exc.code, str(exc), exc.ctx)
                total_smartcut += batch_smartcut

            # --- ROUTER ---
            elif router_allowed and router_pending > 0:
                logger.info(
                    f"{COLOR_YELLOW}🎲 Choix: Router (valeur={choice_value:.2f}, ratio={ratio_smartcut}){COLOR_RESET}"
                )
                logger.info(
                    f"{COLOR_BLUE}🚀 Lancement RouterWorker ({router_pending} vidéos non conformes){COLOR_RESET}"
                )
                try:
                    worker = RouterWorker(limit_videos=CM_NB_VID_ROUTER)
                    worker.run()
                    batch_router = router_pending
                    total_router += batch_router
                except CutMindError as exc:
                    logger.exception("[%s] %s | ctx=%r", exc.code, str(exc), exc.ctx)

            # --- ROUTER BLOQUÉ (NUIT) ---
            elif not router_allowed:
                logger.info(f"{COLOR_RED}🌙 Plage horaire silencieuse — Router désactivé (SmartCut forcé){COLOR_RESET}")
                if smartcut_pending > 0:
                    try:
                        batch_smartcut = process_smartcut_batch(
                            smartcut_videos, smartcut_dirs, SMARTCUT_BATCH, logger=logger
                        )
                    except CutMindError as exc:
                        logger.exception("[%s] %s | ctx=%r", exc.code, str(exc), exc.ctx)
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
            try:
                reload_and_apply(logger=logger)
            except CutMindError as exc:
                logger.exception("[%s] %s | ctx=%r", exc.code, str(exc), exc.ctx)
            time.sleep(SCAN_INTERVAL)
            try:
                validation(logger=logger)
            except CutMindError as exc:
                logger.exception("[%s] %s | ctx=%r", exc.code, str(exc), exc.ctx)

            # 🔹 Import CSV automatique dans CutMind
            logger.info("📥 Import SmartCut CSVs vers CutMind...")
            try:
                update_segments_csv(logger=logger)
            except CutMindError as exc:
                logger.exception("[%s] %s | ctx=%r", exc.code, str(exc), exc.ctx)
            try:
                if is_in_audit_window(start_audit, end_audit):
                    logger.info(f"{COLOR_BLUE}🚀 Lancement du l'Audit Check){COLOR_RESET}")
                    main_check_script()
            except CutMindError as exc:
                logger.exception("[%s] %s | ctx=%r", exc.code, str(exc), exc.ctx)

        except Exception as err:
            logger.exception(f"{COLOR_RED}💥 Erreur inattendue orchestrateur : {err}{COLOR_RESET}")
            time.sleep(30)
