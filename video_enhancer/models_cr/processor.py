""" """

from __future__ import annotations

from pathlib import Path

from shared.executors.ffmpeg_utils import detect_nvenc_available
from shared.executors.ffprobe_utils import (
    get_fps,
    get_resolution,
    get_total_frames,
    has_audio,
)
from shared.models.db_models import Segment
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.services.ensure_deinterlaced import ensure_deinterlaced
from shared.services.file_mover import FileMover
from shared.services.video_preparation import VideoPrepared, prepare_video
from shared.status_orchestrator.statuses import OrchestratorStatus
from shared.utils.config import (
    COLOR_BLUE,
    COLOR_CYAN,
    COLOR_GREEN,
    COLOR_PURPLE,
    COLOR_RED,
    COLOR_RESET,
    COLOR_YELLOW,
)
from shared.utils.datas import resolution_str_to_tuple
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from shared.utils.settings import get_settings
from video_enhancer.models_cr.processed_segment import ProcessedSegment
from video_enhancer.models_cr.videojob import VideoJob
from video_enhancer.services.check_fix import check_fix_workflow
from video_enhancer.services.cleanup import cleanup_enhanced_dirs
from video_enhancer.services.workflow import run_enhancement_workflow


class VideoProcessor:
    @with_child_logger
    def __init__(
        self,
        segment: Segment | None = None,
        logger: LoggerProtocol | None = None,
    ) -> None:
        logger = ensure_logger(logger, __name__)
        self.segment = segment

    @with_child_logger
    def process(
        self,
        video_path: Path,
        force_deinterlace: bool = False,
        logger: LoggerProtocol | None = None,
    ) -> ProcessedSegment:
        logger = ensure_logger(logger, __name__)
        settings = get_settings()
        CLEANUP = settings.router_processor.cleanup

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
            job = VideoJob(
                path=video_path,
                work_key=f"seg_{self.segment.id}_{self.segment.uid}",
                fps_in=self.segment.fps or get_fps(video_path),
                resolution=(
                    resolution_str_to_tuple(self.segment.resolution)
                    if self.segment.resolution
                    else resolution_str_to_tuple(get_resolution(video_path))
                ),
                has_audio=self.segment.has_audio or has_audio(video_path),
                nb_frames=self.segment.nb_frames or get_total_frames(video_path),
                codec_in=self.segment.codec,
                bitrate_in=self.segment.bitrate,
                filesize_mb_in=(
                    self.segment.filesize_mb
                    if self.segment.filesize_mb
                    else round(video_path.stat().st_size / (1024 * 1024), 2)
                ),
                duration_in=(
                    self.segment.duration
                    if self.segment.duration
                    else prepare_video(video_path, logger=logger).duration
                ),
            )

            logger.info(
                "Processing plan | upscale=%s | interpolation_method=%s | rife_passes=%s",
                job.upscale_factor,
                job.interpolation_method,
                job.rife_passes,
            )

            use_nvenc = detect_nvenc_available()
            if use_nvenc:
                cuda = True
            else:
                cuda = False

            # 🧩 Étape 1 : détection / désentrelacement
            job.path = ensure_deinterlaced(
                video_path, use_cuda=cuda, cleanup=CLEANUP, has_audio=job.has_audio, logger=logger
            )
            # 🧩 Étape 2 : workflow enhancement
            job.path = run_enhancement_workflow(job=job, logger=logger)
            # 🧩 Étape 3 : check & fix
            job, self.segment, meta = check_fix_workflow(job=job, segment=self.segment, cuda=cuda, logger=logger)

            if not self.segment or not self.segment.output_path or not self.segment.id or not self.segment.uid:
                raise CutMindError(
                    "❌ Erreur inattendue : Vidéo inconnue.",
                    code=ErrCode.UNEXPECTED,
                    ctx=get_step_ctx({"video_path": str(video_path)}),
                )

            # 🧩 Étape 4 : Move
            logger.debug(f"for _notif -> final_output : {job.path}")
            self._notify_cutmind(job, logger=logger)
            logger.debug("sortie notify")

            # 🧩 Étape 5 : Mise à jour DB
            new_seg = ProcessedSegment(
                id=self.segment.id,
                status=OrchestratorStatus.SEGMENT_ENHANCED,
                source_flow=f"upscale_factor={job.upscale_factor} | rife_passes={job.rife_passes}",
                fps=job.fps_out,
                resolution=meta.resolution,
                nb_frames=meta.nb_frames,
                codec=meta.codec,
                bitrate=meta.bitrate,
                filesize_mb=meta.filesize_mb,
                tags=self.segment.tags,
                duration=meta.duration,
                processed_by="enhancer_router",
                output_path=Path(self.segment.output_path),
            )
            logger.debug(f"new_seg : {new_seg}")
            self.log_summary(job=job, meta=meta, logger=logger)
            logger.debug("sortie summary")

            # 🧩 Étape 6 : Nettoyage
            if CLEANUP:
                cleanup_enhanced_dirs(logger=logger)

            logger.info(f"✅ Terminé : {job.path.name}")
            return new_seg

        except CutMindError:
            raise
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur innatendue Enhancer.",
                code=ErrCode.UNEXPECTED,
                ctx=get_step_ctx(
                    {
                        "job.path.name": job.path.name,
                        "segment": self.segment.filename_predicted,
                    }
                ),
            ) from exc

    def _notify_cutmind(
        self,
        job: VideoJob,
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
            logger.debug(f"🔄 Remplacement direct par copie transactionnelle : {job.path} → {target_path}")

            # --- 🛠️ Remplacement
            try:
                logger.debug(
                    "appel safe_replace : final_output=%s, target_path=%s",
                    job.path,
                    target_path,
                )
                FileMover.safe_replace(job.path, target_path, logger)
                logger.info(
                    "📦 Fichier remplacé (via safe_copy) : %s → %s",
                    job.path.name,
                    target_path,
                )

            except Exception as move_err:
                raise CutMindError(
                    "❌ Impossible de déplacer le fichier.",
                    code=ErrCode.NOFILE,
                    ctx=get_step_ctx(
                        {
                            "final_output": job.path,
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
                            "final_output": job.path,
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
            f"{COLOR_RESET} → {COLOR_GREEN}{fmt_float(job.fps_out)}{COLOR_RESET}"
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
