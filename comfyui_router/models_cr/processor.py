""" """

from __future__ import annotations

from pathlib import Path
import shutil

from pymediainfo import MediaInfo

from comfyui_router.comfyui.comfyui_command import comfyui_path
from comfyui_router.ffmpeg.deinterlace import ensure_deinterlaced
from comfyui_router.ffmpeg.ffmpeg_command import convert_to_60fps
from comfyui_router.ffmpeg.smart_recut_hybrid import smart_recut_hybrid
from comfyui_router.models_cr.comfy_workflow_manager import ComfyWorkflowManager
from comfyui_router.models_cr.output_manager import OutputManager
from comfyui_router.models_cr.videojob import VideoJob
from comfyui_router.output.output import cleanup_outputs
from cutmind.db.data_utils import format_resolution
from cutmind.db.repository import CutMindRepository
from cutmind.models_cm.db_models import Video
from cutmind.process.file_mover import FileMover
from shared.ffmpeg.ffmpeg_utils import detect_nvenc_available, get_fps, get_resolution
from shared.utils.config import OK_DIR, OUTPUT_DIR, TRASH_DIR
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from shared.utils.settings import get_settings
from shared.utils.trash import move_to_trash, purge_old_trash

settings = get_settings()

FORCE_DEINTERLACE = settings.router_processor.force_deinterlace
CLEANUP = settings.router_processor.cleanup
PURGE_DAYS = settings.router_processor.purge_days
DELTA_DURATION = settings.router_processor.delta_duration
RATIO_DURATION = settings.router_processor.ratio_duration


class VideoProcessor:
    @with_child_logger
    def __init__(
        self,
        cutmind_repo: CutMindRepository | None = None,
        video: Video | None = None,
        logger: LoggerProtocol | None = None,
    ) -> None:
        logger = ensure_logger(logger, __name__)
        self.workflow_mgr = ComfyWorkflowManager()
        self.output_mgr = OutputManager()
        self.repo = cutmind_repo
        self.video = video

    @with_child_logger
    def process(
        self, video_path: Path, force_deinterlace: bool = FORCE_DEINTERLACE, logger: LoggerProtocol | None = None
    ) -> None:
        logger = ensure_logger(logger, __name__)
        if not self.video or not self.video.name:
            logger.warning("🚨 Vidéo inconnue")
            return

        logger.info(f"🎞️ Traitement de {self.video.name} : {self.video.resolution} - {self.video.fps} fps")
        logger.info(f"🚀 Début traitement ComfyUI : {video_path.name} sur {len(self.video.segments)}")

        job = VideoJob(video_path)
        job.analyze(logger=logger)

        use_nvenc = detect_nvenc_available(logger=logger)
        if use_nvenc:
            cuda = True
        else:
            cuda = False

        # 🧩 Étape 2 : détection / désentrelacement
        video_path = ensure_deinterlaced(video_path, use_cuda=cuda, cleanup=CLEANUP, logger=logger)
        video_path = smart_recut_hybrid(video_path, use_cuda=cuda, cleanup=CLEANUP, logger=logger)
        job.path = Path(video_path)
        job.comfyui_path = comfyui_path(full_path=video_path)
        workflow = self.workflow_mgr.prepare_workflow(job, logger=logger)
        if not workflow:
            return

        if not self.workflow_mgr.run(workflow, logger=logger):
            logger.warning(f"❌ Échec traitement ComfyUI : {job.path.name}")
            return

        if not self.output_mgr.wait_for_output(job, logger=logger):
            logger.warning(f"❌ Fichier de sortie introuvable : {job.path.name}")
            return

        if not job.output_file:
            return
        job.fps_out = get_fps(job.output_file)
        job.resolution_out = get_resolution(job.output_file)
        final_output = OK_DIR / job.output_file.name
        logger.debug(f"✅ OK_DIR : {OK_DIR}, TRASH_DIR : {TRASH_DIR}")
        logger.debug(f"✅ Fichier de sortie trouvé : {final_output}")

        if job.fps_out > 60:
            temp_output = final_output.with_name(f"{job.path.stem}_60fps.mp4")
            logger.debug(f"fps_out > 60 -> temp_output : {temp_output}")
            if convert_to_60fps(job.output_file, temp_output, logger=logger):
                job.output_file.unlink()
                final_output = temp_output
                logger.debug(f"fps_out > 60 -> final_output : {final_output}")
        elif job.fps_out < 59:
            retry_path = job.path.parent / f"{job.path.name}"
            logger.debug(f"fps_out < 60 -> retry_path : {retry_path}")
            self._notify_cutmind(job, retry_path, status="rejected", logger=logger)
            # shutil.move(job.output_file, retry_path)
            logger.info(f"↩️ Rejet : {job.path.name} (FPS {job.fps_out:.2f})")

            return
        else:
            shutil.move(job.output_file, final_output)

        move_to_trash(file_path=job.path, trash_root=TRASH_DIR)
        cleanup_outputs(video_path.stem, final_output, OUTPUT_DIR, logger=logger)
        purge_old_trash(trash_root=TRASH_DIR, days=PURGE_DAYS, logger=logger)
        logger.info(f"🧹 Nettoyage des fichiers intermédiaires terminé pour {video_path.stem}")
        logger.info(f"✅ Terminé : {final_output.name}")
        logger.debug(f"for _notif -> final_output : {final_output}")
        self._notify_cutmind(job, final_output, status="enhanced", logger=logger)

    @with_child_logger
    def _notify_cutmind(
        self,
        job: VideoJob,
        final_output: Path,
        status: str,
        replace_original: bool = True,
        logger: LoggerProtocol | None = None,
    ) -> None:
        logger = ensure_logger(logger, __name__)

        if not self.repo:
            return

        try:
            seg_uid = job.path.stem.split("_")[2]
            seg = self.repo.get_segment_by_uid(seg_uid, logger=logger)
            logger.debug(f"_notify_cutmind seg_uid : {seg_uid}")

            if not seg:
                logger.warning("⚠️ Segment UID introuvable : %s", seg_uid)
                return

            if replace_original:
                if not seg.output_path:
                    logger.error("❌ Segment sans chemin de sortie défini : %s", seg.uid)
                    return

                target_path = Path(seg.output_path)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                logger.debug(f"🔄 Remplacement direct par copie transactionnelle : {final_output} → {target_path}")

                # --- ⚠️ Vérification durée avant remplacement ---
                try:
                    media_info = MediaInfo.parse(final_output)
                    duration_real = None
                    for track in media_info.tracks:
                        if track.track_type == "Video" and track.duration:
                            duration_real = round(track.duration / 1000, 3)
                            break

                    if duration_real and seg.duration:
                        expected = round(seg.duration, 3)
                        delta = abs(duration_real - expected)
                        ratio = delta / expected if expected else 0

                        if delta > DELTA_DURATION or ratio > RATIO_DURATION:
                            logger.warning(
                                "⏱️ ⚠️ Écart de durée segment %s : attendu=%.2fs / réel=%.2fs (∆ %.2fs, %.1f%%)",
                                seg.uid,
                                expected,
                                duration_real,
                                delta,
                                ratio * 100,
                            )
                            if not seg.tags or "duration_warning" not in seg.tags:
                                seg.add_tag("duration_warning")
                    elif not duration_real:
                        logger.warning("⏱️ Impossible de lire la durée de sortie pour %s", final_output)

                except Exception as dur_err:
                    logger.error("❌ Erreur analyse durée finale : %s", final_output)
                    logger.exception(str(dur_err))

                # --- 🛠️ Remplacement
                try:
                    FileMover.safe_replace(final_output, target_path, logger=logger)
                    logger.info("📦 Fichier remplacé (via safe_copy) : %s → %s", final_output.name, target_path)

                except Exception as move_err:
                    logger.error("❌ Impossible de déplacer le fichier : %s → %s", final_output, target_path)
                    logger.exception(str(move_err))
                    return

                if not target_path.exists():
                    logger.error("❌ Fichier manquant après remplacement : %s", target_path)
                    return

            else:
                logger.info("ℹ️ Remplacement original désactivé — fichier conservé dans OK_DIR")

            # --- Mise à jour DB
            seg.status = status
            seg.source_flow = "comfyui_router"
            seg.fps = getattr(job, "fps_out", None)
            seg.resolution = format_resolution(job.resolution_out, logger=logger)
            seg.processed_by = job.workflow_name or "comfyui_router"
            if not replace_original:
                seg.output_path = str(final_output)

            self.repo.update_segment_postprocess(seg, logger=logger)
            logger.info("🧠 CutMind synchronisé pour segment %s (%s)", seg.uid, status)

        except Exception as err:
            logger.exception("❌ Erreur notification CutMind pour %s : %s", job.path.name, err)
