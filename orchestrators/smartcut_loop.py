from pathlib import Path
import time

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.services.file_mover import FileMover
from shared.utils.config import IMPORT_DIR_SC, OUTPUT_DIR_SC, TRASH_DIR_SC, WORK_DIR_SC
from shared.utils.logger import LoggerProtocol, ensure_logger, get_logger
from shared.utils.trash import move_to_trash
from smartcut.smartcut import multi_stage_cut
from smartcut.smartcut_lite import lite_cut


def smartcut_loop() -> None:
    logger = get_logger("CutMind-SmartCut")
    from shared.models.config_manager import bootstrap_process

    bootstrap_process(logger=logger)
    from shared.utils.settings import get_settings

    settings = get_settings()
    SMARTCUT_BATCH = settings.smartcut.batch_size
    SCAN_INTERVAL = settings.smartcut.scan_interval
    SMARTCUT_ENABLED = settings.router_orchestrator.smartcut

    back_to_imports(
        path_in=WORK_DIR_SC,
        path_out=IMPORT_DIR_SC,
        logger=logger,
    )

    while True:
        try:
            if not SMARTCUT_ENABLED:
                logger.info("🚫 SmartCut est désactivé dans les settings. Loop inactive.")
                time.sleep(SCAN_INTERVAL)
            else:
                videos, dirs = list_videos_and_dirs(IMPORT_DIR_SC)
                pending = len(videos) + len(dirs)

                if pending == 0:
                    logger.info("📂 SmartCut: rien à traiter")
                    time.sleep(SCAN_INTERVAL)

                else:
                    process_smartcut_batch(
                        videos,
                        dirs,
                        SMARTCUT_BATCH,
                        logger=logger,
                    )

        except Exception:
            logger.exception("💥 Erreur SmartCut loop")
            time.sleep(30)


# ============================================================
# 🔁 Traitement par lot SmartCut
# ============================================================
def list_videos_and_dirs(directory: Path) -> tuple[list[Path], list[Path]]:
    video_exts = (".mp4", ".mov", ".mkv", ".avi", ".wmv")
    videos = [p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in video_exts]
    dirs = [p for p in directory.iterdir() if p.is_dir()]
    return videos, dirs


def process_smartcut_batch(
    videos: list[Path], dirs: list[Path], max_items: int, logger: LoggerProtocol | None = None
) -> int:
    """
    Traite un lot limité de vidéos/dossiers SmartCut.

    Retourne le nombre total traités.
    """
    logger = ensure_logger(logger, __name__)
    file_mover = FileMover()
    try:
        count = 0
        for video_path in videos:
            sc_path = WORK_DIR_SC / video_path.name
            file_mover.safe_replace(src=video_path, dst=sc_path, logger=logger)
            process_smartcut_video(sc_path)
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
        raise err.with_context(get_step_ctx({"nb_videos": len(videos), "nb_folders": len(dirs)})) from err
    except Exception as exc:
        raise CutMindError(
            "Unexpected error in Smartcut batch",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"nb_videos": len(videos), "nb_folders": len(dirs)}),
        ) from exc


# ============================================================
# 📦 Traitement SmartCut complet
# ============================================================
def process_smartcut_video(video_path: Path) -> None:
    logger = get_logger("CutMind-SmartCut")
    from shared.utils.settings import get_settings

    settings = get_settings()
    USE_CUDA = settings.smartcut.use_cuda
    try:
        logger.info(f"🚀 SmartCut (complet) : {video_path.name}")

        multi_stage_cut(video_path=video_path, out_dir=OUTPUT_DIR_SC, use_cuda=USE_CUDA, logger=logger)

    except CutMindError as err:
        raise err.with_context(get_step_ctx({"video_path.name": video_path.name})) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur lors du process Smartcut.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video_path.name": video_path.name}),
        ) from exc


def process_smartcut_folder(folder_path: Path) -> None:
    """
    Flow SmartCut Lite (segments déjà présents dans un dossier).
    """
    logger = get_logger("CutMind-SmartCutLite")
    try:
        logger.info(f"🚀 SmartCut Lite : dossier {folder_path.name}")
        lite_cut(directory_path=folder_path)

    except CutMindError as err:
        raise err.with_context(get_step_ctx({"folder_path.name": folder_path.name})) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur lors du process Smartcut Lite.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"folder_path.name": folder_path.name}),
        ) from exc


def back_to_imports(path_in: Path, path_out: Path, logger: LoggerProtocol | None = None) -> None:
    """
    Déplace les vidéos non traitées vers le dossier d'import.
    """
    logger = ensure_logger(logger, __name__)
    file_mover = FileMover()
    videos, _ = list_videos_and_dirs(path_in)
    pending = len(videos)

    if pending == 0:
        logger.info("📂 SmartCut: workdir propre, rien renvoyer")
        return
    try:
        for video_path in videos:
            if video_path.name.endswith("_conv.mp4"):
                move_to_trash(video_path, TRASH_DIR_SC)
                logger.info(f"🗑️ Vidéo de conversion supprimée : {video_path.name}")
            else:
                sc_path = path_out / video_path.name
                file_mover.safe_replace(src=video_path, dst=sc_path, logger=logger)
                logger.info(f"📂 Vidéo renvoyée vers imports : {video_path.name}")
        return
    except CutMindError as err:
        raise err.with_context(get_step_ctx({"nb_videos": len(videos)})) from err
    except Exception as exc:
        raise CutMindError(
            "Unexpected error in Smartcut batch",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"nb_videos": len(videos)}),
        ) from exc
