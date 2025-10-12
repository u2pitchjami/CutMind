from pathlib import Path
import shutil

from comfyui_router.ffmpeg.ffmpeg_command import (
    convert_to_60fps,
    ensure_deinterlaced,
    get_fps,
)
from comfyui_router.models.comfy_workflow_manager import ComfyWorkflowManager
from comfyui_router.models.output_manager import OutputManager
from comfyui_router.models.videojob import VideoJob
from comfyui_router.output.output import cleanup_outputs
from comfyui_router.utils.config import OK_DIR, TRASH_DIR, OUTPUT_DIR
from comfyui_router.utils.logger import get_logger

logger = get_logger("Comfyui Router")


class VideoProcessor:
    def __init__(self) -> None:
        self.logger = logger
        self.workflow_mgr = ComfyWorkflowManager()
        self.output_mgr = OutputManager()

    def process(self, video_path: Path, force_deinterlace: bool = False) -> None:
        self.logger.info(f"🚀 Début traitement ComfyUI : {video_path.name}")
        job = VideoJob(video_path)
        job.analyze()

        # 🧩 Étape 2 : détection / désentrelacement
        video_path = ensure_deinterlaced(video_path, use_cuda=True, cleanup=True)

        workflow = self.workflow_mgr.prepare_workflow(job)
        if not workflow:
            return

        if not self.workflow_mgr.run(workflow):
            self.logger.warning(f"❌ Échec traitement ComfyUI : {job.path.name}")
            return

        if not self.output_mgr.wait_for_output(job):
            self.logger.warning(f"❌ Fichier de sortie introuvable : {job.path.name}")
            return

        if not job.output_file:
            return
        job.fps_out = get_fps(job.output_file)
        final_output = OK_DIR / job.output_file.name
        logger.debug(f"✅ OK_DIR : {OK_DIR}, TRASH_DIR : {TRASH_DIR}")
        logger.debug(f"✅ Fichier de sortie trouvé : {final_output}")

        if job.fps_out > 60:
            temp_output = final_output.with_name(f"{job.path.stem}_60fps.mp4")
            if convert_to_60fps(job.output_file, temp_output):
                job.output_file.unlink()
                final_output = temp_output
        elif job.fps_out < 59:
            retry_path = job.path.parent / f"RETRY_{job.path.name}"
            shutil.move(job.output_file, retry_path)
            self.logger.info(f"↩️ Rejet : {job.path.name} (FPS {job.fps_out:.2f})")
            return
        else:
            shutil.move(job.output_file, final_output)

        shutil.move(job.path, TRASH_DIR / job.path.name)
        cleanup_outputs(video_path.stem, final_output, OUTPUT_DIR)
        self.logger.info(f"🧹 Nettoyage des fichiers intermédiaires terminé pour {video_path.stem}")
        self.logger.info(f"✅ Terminé : {final_output.name}")
