# actions/process_already_enhanced.py

from pathlib import Path
from shutil import copy2

from comfyui_router.services.smart_recut_hybrid import smart_recut_hybrid
from cutmind.db.repository import CutMindRepository
from cutmind.process.file_mover import FileMover
from shared.executors.ffmpeg_utils import detect_nvenc_available
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.models.timer_manager import Timer
from shared.services.ensure_deinterlaced import ensure_deinterlaced
from shared.services.ensure_resolution import ensure_resolution
from shared.services.video_preparation import prepare_video
from shared.utils.config import WORKDIR_CM
from shared.utils.datas import format_resolution, resolution_str_to_tuple
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from shared.utils.safe_segments import safe_segments
from shared.utils.settings import get_settings

settings = get_settings()

CLEANUP = settings.router_processor.cleanup


@safe_segments
@with_child_logger
def process_standard_videos(limit: int = 10, logger: LoggerProtocol | None = None) -> None:
    logger = ensure_logger(logger, __name__)
    repo = CutMindRepository()
    uids = repo.get_standard_videos(limit)

    if not Path(WORKDIR_CM).exists():
        Path(WORKDIR_CM).mkdir(parents=True)

    try:
        for uid in uids:
            video = repo.get_video_with_segments(uid)
            if not video:
                logger.warning("⏩ Vidéo ignorée (données manquantes) : %s", uid)
                continue
            logger.info("▶️ Traitement vidéo : %s", video.name)
            logger.debug(f"video : {video}")

            all_done = True

            with Timer(f"Traitement vidéo enhanced : {video.name}", logger):
                for seg in video.segments:
                    if not seg.filename_predicted or not seg.output_path or not seg.resolution or not seg.id:
                        logger.warning("⏩ Segment ignoré (données manquantes) : %s", seg.uid)
                        continue
                    seg_path = Path(str(seg.output_path))
                    logger.debug(f"seg_path : {seg_path}")
                    if not seg_path.exists():
                        logger.warning("⚠️ Fichier manquant pour segment : %s", seg.uid)
                        all_done = False
                        continue

                    use_nvenc = detect_nvenc_available()
                    if use_nvenc:
                        cuda = True
                    else:
                        cuda = False
                    logger.debug(f"WORKDIR_CM  : {WORKDIR_CM}")

                    temp_path = Path(WORKDIR_CM) / seg_path.name
                    logger.debug(f"temp_path  : {temp_path}")
                    copy2(seg_path, temp_path)

                    # Étape 1 : désentrelacement
                    processed_path = ensure_deinterlaced(temp_path, use_cuda=cuda, cleanup=CLEANUP)

                    # Étape 2 : recut intelligent
                    processed_path = smart_recut_hybrid(processed_path, use_cuda=cuda, cleanup=CLEANUP)

                    # Étape 3 : resize intelligent
                    processed_path, resolution_out = ensure_resolution(
                        processed_path, resolution_str_to_tuple(seg.resolution), logger=logger
                    )
                    if seg.resolution != format_resolution(resolution_out):
                        seg.add_tag("resolution_fixed")
                    # Vérifie si le chemin a changé (fichier modifié)
                    # if processed_path.name != seg_path.name:
                    #     final_path = seg_path.parent / seg.filename_predicted
                    #     processed_path.rename(final_path)
                    #     logger.info("💾 Nouveau fichier : %s", final_path)
                    # else:
                    #     final_path = seg_path

                    # --- 🛠️ Remplacement
                    try:
                        FileMover.safe_replace(processed_path, seg_path)
                        logger.info("📦 Fichier remplacé (via safe_copy) : %s → %s", processed_path.name, seg_path)

                    except Exception as move_err:
                        logger.error("❌ Impossible de déplacer le fichier : %s → %s", processed_path, seg_path)
                        logger.exception(str(move_err))
                        return

                    seg.status = "enhanced"
                    seg.source_flow = "pre_enhanced_bypass"
                    repo.update_segment_validation(seg)
                    if seg.resolution != format_resolution(resolution_out):
                        prep = prepare_video(Path(seg.output_path))
                        repo.update_segment_from_metadata(seg.id, prep)
                    logger.info("✅ Segment %s mis à jour", seg.uid)

            if all_done:
                video.status = "enhanced"
                repo.update_video(video)
                logger.info("🎬 Vidéo %s marquée comme 'enhanced'", video.uid)
            else:
                logger.warning("❌ Tous les segments n’ont pas été traités pour %s", video.uid)
    except CutMindError as err:
        raise err.with_context(get_step_ctx({"uid": uid})) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue process_standard_videos.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"uid": uid}),
        ) from exc
