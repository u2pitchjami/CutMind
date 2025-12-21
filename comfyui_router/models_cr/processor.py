""" """

from __future__ import annotations

from pathlib import Path
import shutil

from comfyui_router.executors.comfyui.comfyclient import ComfyClientREST
from comfyui_router.executors.comfyui.comfyui_command import comfyui_path
from comfyui_router.executors.output import cleanup_outputs
from comfyui_router.ffmpeg.ffmpeg_command import convert_to_60fps
from comfyui_router.models_cr.comfy_workflow_manager import ComfyWorkflowManager
from comfyui_router.models_cr.output_manager import OutputManager
from comfyui_router.models_cr.processed_segment import ProcessedSegment
from comfyui_router.models_cr.videojob import VideoJob
from comfyui_router.services.smart_recut_hybrid import smart_recut_hybrid
from cutmind.models_cm.db_models import Segment
from cutmind.process.file_mover import FileMover
from shared.executors.ffmpeg_utils import detect_nvenc_available
from shared.executors.ffprobe_utils import get_fps, get_resolution, get_total_frames, has_audio
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.services.ensure_deinterlaced import ensure_deinterlaced
from shared.services.ensure_resolution import ensure_resolution
from shared.services.video_preparation import VideoPrepared, prepare_video
from shared.utils.config import (
    COLOR_BLUE,
    COLOR_CYAN,
    COLOR_GREEN,
    COLOR_PURPLE,
    COLOR_RED,
    COLOR_RESET,
    COLOR_YELLOW,
    OK_DIR,
    OUTPUT_DIR,
    TRASH_DIR,
)
from shared.utils.datas import resolution_str_to_tuple
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
        segment: Segment | None = None,
        logger: LoggerProtocol | None = None,
    ) -> None:
        logger = ensure_logger(logger, __name__)
        self.workflow_mgr = ComfyWorkflowManager()
        self.output_mgr = OutputManager()
        self.segment = segment

    @with_child_logger
    def process(
        self, video_path: Path, force_deinterlace: bool = FORCE_DEINTERLACE, logger: LoggerProtocol | None = None
    ) -> ProcessedSegment:
        logger = ensure_logger(logger, __name__)
        if not self.segment or not self.segment.output_path or not self.segment.id or not self.segment.uid:
            raise CutMindError(
                "❌ Erreur inattendue : Vidéo inconnue.",
                code=ErrCode.UNEXPECTED,
                ctx=get_step_ctx({"video_path": str(video_path)}),
            )

        logger.info(
            f"🎞️ Traitement de {self.segment.filename_predicted} : {self.segment.resolution} - {self.segment.fps} fps"
        )

        try:
            job = VideoJob(video_path)
            job.fps_in = self.segment.fps or get_fps(video_path)
            job.resolution = (
                resolution_str_to_tuple(self.segment.resolution)
                if self.segment.resolution
                else resolution_str_to_tuple(get_resolution(video_path))
            )
            job.has_audio = self.segment.has_audio or has_audio(video_path)
            job.nb_frames = self.segment.nb_frames or get_total_frames(video_path)
            job.codec_in = self.segment.codec
            job.bitrate_in = self.segment.bitrate
            job.filesize_mb_in = (
                self.segment.filesize_mb
                if self.segment.filesize_mb
                else round(video_path.stat().st_size / (1024 * 1024), 2)
            )
            job.duration_in = self.segment.duration if self.segment.duration else prepare_video(video_path).duration

            use_nvenc = detect_nvenc_available()
            if use_nvenc:
                cuda = True
            else:
                cuda = False

            # 🧩 Étape 2 : détection / désentrelacement
            video_path = ensure_deinterlaced(video_path, use_cuda=cuda, cleanup=CLEANUP, logger=logger)
            video_path = smart_recut_hybrid(video_path, use_cuda=cuda, cleanup=CLEANUP, logger=logger)
            job.path = Path(video_path)
            job.comfyui_path = comfyui_path(full_path=video_path)
            workflow = self.workflow_mgr.prepare_workflow(job)
            if not workflow:
                raise CutMindError(
                    "❌ Ignorée (résolution trop basse).",
                    code=ErrCode.VIDEO,
                    ctx=get_step_ctx({"video_path": str(video_path)}),
                )

            # --- Lancement ComfyUI via REST
            client = ComfyClientREST()

            client.set_on_start(lambda pid: logger.info(f"🚀 ComfyUI job démarré : {pid}"))
            client.set_on_progress(lambda pid, status: logger.info(f"⏳ ComfyUI [{pid}] statut REST = {status}"))
            client.set_on_error(lambda pid, err: logger.error(f"❌ ComfyUI erreur [{pid}] : {err}"))
            client.set_on_complete(lambda pid, files: logger.info(f"🎉 ComfyUI terminé REST [{pid}] : {files}"))

            # 🟦 Étape 1 : envoi du workflow
            prompt_id = client.submit_prompt(workflow)

            # 🟧 Étape 2 : Attente REST LIGHT (ne bloque pas le Processor longtemps)
            client.wait_for_completion(
                prompt_id,
                timeout=20,  # Très court → juste vérifier que le workflow part bien
                poll_interval=1.0,
            )

            logger.info("📡 ComfyUI REST OK → surveillance réelle par OutputManager...")

            # 🟥 Étape 3 : attente basée sur le vrai fichier généré
            output_path = self.output_mgr.wait_for_output(job)

            if output_path is None:
                raise CutMindError(
                    "❌ Workflow ComfyUI terminé mais aucun fichier de sortie détecté.",
                    code=ErrCode.VIDEO,
                    ctx=get_step_ctx({"video_path": str(video_path)}),
                )

            # 🔧 Définition officielle du fichier final
            job.output_file = output_path
            logger.info(f"📦 Fichier final détecté : {job.output_file}")

            meta = prepare_video(job.output_file)
            job.fps_out = meta.fps
            job.resolution_out = resolution_str_to_tuple(meta.resolution)
            final_output = OK_DIR / job.output_file.name
            res_out = job.resolution_out
            job.output_file, job.resolution_out = ensure_resolution(job.path, job.resolution_out, logger=logger)
            if job.resolution_out != res_out:
                self.segment.add_tag("resolution_fixed")
            logger.debug(f"✅ OK_DIR : {OK_DIR}, TRASH_DIR : {TRASH_DIR}")
            logger.debug(f"✅ Fichier de sortie trouvé : {final_output}")

            try:
                if meta.duration and self.segment.duration:
                    expected = round(self.segment.duration, 3)
                    delta = abs(meta.duration - expected)
                    ratio = delta / expected if expected else 0

                    if delta > DELTA_DURATION or ratio > RATIO_DURATION:
                        logger.warning(
                            "⏱️ ⚠️ Écart de durée segment %s : attendu=%.2fs / réel=%.2fs (∆ %.2fs, %.1f%%)",
                            self.segment.id,
                            expected,
                            meta.duration,
                            delta,
                            ratio * 100,
                        )
                        if self.segment.tags == "" or "duration_warning" not in self.segment.tags:
                            self.segment.add_tag("duration_warning")
                elif not meta.duration:
                    logger.warning("⏱️ Impossible de lire la durée de sortie pour %s", final_output)

            except Exception as dur_err:
                logger.error("❌ Erreur analyse durée finale : %s", final_output)
                logger.exception(str(dur_err))

            if job.fps_out > 60:
                temp_output = final_output.with_name(f"{job.path.stem}_60fps.mp4")
                logger.debug(f"fps_out > 60 -> temp_output : {temp_output}")
                if convert_to_60fps(job.output_file, temp_output):
                    logger.info(f"✅ Conversion 60 FPS terminée : {job.path.stem}")
                    job.output_file.unlink()
                    final_output = temp_output
                    logger.debug(f"fps_out > 60 -> final_output : {final_output}")
                    job.fps_out = get_fps(final_output)
            else:
                shutil.move(job.output_file, final_output)

            move_to_trash(file_path=job.path, trash_root=TRASH_DIR)
            cleanup_outputs(video_path.stem, final_output, OUTPUT_DIR)
            logger.debug(f"🧹 Supprimé : {video_path.stem}")
            purge_old_trash(trash_root=TRASH_DIR, days=PURGE_DAYS, logger=logger)
            logger.info(f"🧹 Nettoyage des fichiers intermédiaires terminé pour {video_path.stem}")
            logger.info(f"✅ Terminé : {final_output.name}")
            logger.debug(f"for _notif -> final_output : {final_output}")
            self._notify_cutmind(job, final_output, logger=logger)
            logger.debug("sortie notify")
            # --- Mise à jour DB

            new_seg = ProcessedSegment(
                id=self.segment.id,
                status="enhanced",
                source_flow="comfyui_router",
                fps=job.fps_out,
                resolution=meta.resolution,
                nb_frames=meta.nb_frames,
                codec=meta.codec,
                bitrate=meta.bitrate,
                filesize_mb=meta.filesize_mb,
                tags=self.segment.tags,
                duration=meta.duration,
                processed_by="comfyui_router",
                output_path=Path(self.segment.output_path),
            )
            logger.debug(f"new_seg : {new_seg}")
            self.log_summary(job=job, meta=meta, logger=logger)
            logger.debug("sortie summary")
            return new_seg

        except CutMindError as err:
            raise err.with_context(get_step_ctx({"segment": self.segment.filename_predicted})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur innatendue Processor Comfyui.",
                code=ErrCode.UNEXPECTED,
                ctx=get_step_ctx({"job.path.name": job.path.name, "segment": self.segment.filename_predicted}),
            ) from exc

    @with_child_logger
    def _notify_cutmind(
        self,
        job: VideoJob,
        final_output: Path,
        logger: LoggerProtocol | None = None,
    ) -> None:
        logger = ensure_logger(logger, __name__)

        if not self.segment or not self.segment.id:
            raise CutMindError(
                "❌ Erreur inattendue : Vidéo inconnue.",
                code=ErrCode.UNEXPECTED,
                ctx=get_step_ctx({"video_path": str(job.path)}),
            )
        try:
            if not self.segment.output_path:
                raise CutMindError(
                    "❌ Segment sans chemin de sortie défini.",
                    code=ErrCode.NOFILE,
                    ctx=get_step_ctx({"seg_id": self.segment.id, "job.path": str(job.path)}),
                )

            target_path = Path(self.segment.output_path)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            logger.debug(f"🔄 Remplacement direct par copie transactionnelle : {final_output} → {target_path}")

            # --- ⚠️ Vérification durée avant remplacement ---

            # --- 🛠️ Remplacement
            try:
                FileMover.safe_replace(final_output, target_path)
                logger.info("📦 Fichier remplacé (via safe_copy) : %s → %s", final_output.name, target_path)

            except Exception as move_err:
                raise CutMindError(
                    "❌ Impossible de déplacer le fichier.",
                    code=ErrCode.NOFILE,
                    ctx=get_step_ctx(
                        {
                            "final_output": final_output,
                            "target_path": target_path,
                            "seg_id": self.segment.id,
                            "job.path": str(job.path),
                        }
                    ),
                ) from move_err

            if not target_path.exists():
                raise CutMindError(
                    "❌ Fichier manquant après remplacement.",
                    code=ErrCode.NOFILE,
                    ctx=get_step_ctx(
                        {
                            "final_output": final_output,
                            "target_path": target_path,
                            "seg_id": self.segment.id,
                            "job.path": str(job.path),
                        }
                    ),
                )
        except CutMindError as err:
            raise err.with_context(get_step_ctx({"seg_id": self.segment.id})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur innatendue notification CutMind.",
                code=ErrCode.UNEXPECTED,
                ctx=get_step_ctx({"job.path.name": job.path.name, "seg_uid": self.segment.uid}),
            ) from exc

    @with_child_logger
    def log_summary(self, job: VideoJob, meta: VideoPrepared, logger: LoggerProtocol | None = None) -> None:
        """
        Log un résumé coloré du traitement ComfyUI avec gestion robuste des valeurs None.
        """
        logger = ensure_logger(logger, __name__)
        logger.debug("entrée summary")

        # Helpers sûrs
        def fmt_float(v: float | int | None) -> str:
            if v is None:
                return "N/A"
            try:
                return f"{float(v):.2f}"
            except Exception:
                return "N/A"

        logger.debug("fin fmt_float")

        def fmt_tuple(t: tuple[int, int] | None) -> str:
            if isinstance(t, tuple) and len(t) == 2:
                return f"{t[0]}x{t[1]}"
            return "N/A"

        logger.debug("fin fmt_str")

        def fmt_str(v: str | None) -> str:
            return v if isinstance(v, str) else "N/A"

        logger.info(f"{COLOR_PURPLE}🧾 Résumé traitement ComfyUI pour : {COLOR_CYAN}{job.path.name}{COLOR_RESET}")

        # 📌 FPS
        logger.info(
            f"{COLOR_BLUE}📌 FPS        : {COLOR_YELLOW}{fmt_float(job.fps_in)}"
            f"{COLOR_RESET} → {COLOR_GREEN}{fmt_float(meta.fps)}{COLOR_RESET}"
        )

        # 📌 Résolution
        logger.info(
            f"{COLOR_BLUE}📌 Résolution : {COLOR_YELLOW}{fmt_tuple(job.resolution)}"
            f"{COLOR_RESET} → {COLOR_GREEN}{fmt_tuple(job.resolution_out)}{COLOR_RESET}"
        )

        # 📌 Codec
        logger.info(
            f"{COLOR_BLUE}📌 Codec      : {COLOR_YELLOW}{fmt_str(job.codec_in)}"
            f"{COLOR_RESET} → {COLOR_GREEN}{fmt_str(meta.codec)}{COLOR_RESET}"
        )

        # 📌 Bitrate
        logger.info(
            f"{COLOR_BLUE}📌 Bitrate    : {COLOR_YELLOW}{fmt_float(job.bitrate_in)} kbps"
            f"{COLOR_RESET} → {COLOR_GREEN}{fmt_float(meta.bitrate)} kbps{COLOR_RESET}"
        )

        # 📌 Taille
        logger.info(
            f"{COLOR_BLUE}📌 Taille     : {COLOR_YELLOW}{fmt_float(job.filesize_mb_in)} MB"
            f"{COLOR_RESET} → {COLOR_GREEN}{fmt_float(meta.filesize_mb)} MB{COLOR_RESET}"
        )

        # 📌 Frames
        logger.info(
            f"{COLOR_BLUE}📌 Frames     : {COLOR_YELLOW}{job.nb_frames}"
            f"{COLOR_RESET} → {COLOR_GREEN}{meta.nb_frames if meta.nb_frames else 'N/A'}{COLOR_RESET}"
        )

        # 📌 Duration
        logger.info(
            f"{COLOR_BLUE}📌 Durée      : {COLOR_YELLOW}{fmt_float(job.duration_in)} s"
            f"{COLOR_RESET} → {COLOR_GREEN}{fmt_float(meta.duration)} s{COLOR_RESET}"
        )

        # 📌 Audio
        logger.info(
            f"{COLOR_BLUE}📌 Audio      : "
            f"{COLOR_GREEN if job.has_audio else COLOR_RED}"
            f"{'Oui' if job.has_audio else 'Non'}{COLOR_RESET}"
        )
