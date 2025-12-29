"""
smart_multicut_auto.py — version stable avec reprise automatique
===============================================================

- Crée ou reprend une session SmartCut (JSON)
- Exécute les étapes du pipeline :
  1. pyscenedetect
  2. analyse IA
  3. merge des segments
  4. cut final
- Sauvegarde l’état à chaque étape
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import uuid

from cutmind.db.repository import CutMindRepository
from cutmind.models_cm.db_models import Segment, Video
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.models.timer_manager import Timer
from shared.services.video_preparation import prepare_video
from shared.utils.config import ERROR_DIR_SC, OUTPUT_DIR_SC, TRASH_DIR_SC
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from shared.utils.settings import get_settings
from shared.utils.trash import move_to_trash, purge_old_trash
from smartcut.executors.analyze.split_utils import get_downscale_factor, move_to_error
from smartcut.services.analyze.apply_confidence import apply_confidence_to_session
from smartcut.services.analyze.ia_pipeline_service import run_ia_pipeline
from smartcut.services.cut_service import CutRequest, CutService
from smartcut.services.merge.merge_service import MergeService
from smartcut.services.scene_split.pipeline_service import adaptive_scene_split

settings = get_settings()

PURGE_DAYS = settings.smartcut.purge_days
USE_CUDA = settings.smartcut.use_cuda
SEED = settings.smartcut.seed
INITIAL_THRESHOLD = settings.smartcut.initial_threshold
MIN_THRESHOLD = settings.smartcut.min_threshold
THRESHOLD_STEP = settings.smartcut.threshold_step
MIN_DURATION = settings.smartcut.min_duration
MAX_DURATION = settings.smartcut.max_duration
FRAME_PER_SEGMENT = settings.smartcut.frame_per_segment
AUTO_FRAMES = settings.smartcut.auto_frames
VCODEC_CPU = settings.smartcut.vcodec_cpu
VCODEC_GPU = settings.smartcut.vcodec_gpu
CRF = settings.smartcut.crf
PRESET_CPU = settings.smartcut.preset_cpu
PRESET_GPU = settings.smartcut.preset_gpu
FPS_EXTRACT = settings.analyse_segment.fps_extract
BASE_RATE = settings.analyse_segment.base_rate
MODEL_CONFIDENCE = settings.analyse_confidence.model_confidence


@with_child_logger
def multi_stage_cut(
    video_path: Path,
    out_dir: Path,
    use_cuda: bool = False,
    seed: int | None = None,
    logger: LoggerProtocol | None = None,
) -> None:
    """
    Pipeline complet SmartCut avec reprise d'état.

    Args:
        video_path: Chemin de la vidéo à traiter
        out_dir: Dossier de sortie
        use_cuda: Utiliser GPU (ffmpeg NVENC)
        seed: Optionnel, seed IA

    Returns:
        Liste des chemins de fichiers exportés
    """
    logger = ensure_logger(logger, __name__)

    # ======================
    # 🧠 Étape 0 : Init session
    # ======================

    repo = CutMindRepository()

    try:
        session = repo.video_exists_by_video_path(str(video_path))

        if not session:
            # 1. Prépare la vidéo (format, durée, fps, etc.)
            prep = prepare_video(video_path)
            orig = Path(video_path).resolve()
            safe = Path(prep.path).resolve()

            if orig != safe:
                logger.info(f"🎞️ Conversion automatique : {orig.name} → {safe.name}")
                move_to_trash(orig, TRASH_DIR_SC)

            # 2. Crée une nouvelle session à partir des métadonnées préparées
            new_vid = Video(
                uid=str(uuid.uuid4()),
                name=prep.path.stem,
                video_path=str(prep.path),
                duration=prep.duration,
                fps=prep.fps,
                nb_frames=prep.nb_frames,
                resolution=prep.resolution,
                codec=prep.codec,
                bitrate=prep.bitrate,
                filesize_mb=prep.filesize_mb,
                has_audio=prep.has_audio,
                audio_codec=prep.audio_codec,
                sample_rate=prep.sample_rate,
                channels=prep.channels,
                audio_duration=prep.audio_duration,
                status="init",
                origin="smartcut",
            )
            repo.insert_video_with_segments(new_vid)
            vid = repo.get_video_with_segments(video_uid=new_vid.uid)
            logger.info("✅ Nouvelle vidéo créée %s : %.2fs @ %.2f FPS", new_vid.name, new_vid.duration, new_vid.fps)
        else:
            vid = repo.get_video_with_segments(video_id=session)
            if not vid or not vid.status:
                raise CutMindError(
                    f"Vidéo introuvable en base de données pour l'ID {session}",
                    code=ErrCode.NOT_FOUND,
                )
            logger.info("♻️ Reprise de session existante %s : %s", vid.name, vid.status)

        # ======================
        # 🎬 Étape 1 : Découpage pyscenedetect
        # ======================
        if not vid or not vid.status or not vid.duration or not vid.id or not vid.video_path:
            raise CutMindError(
                "Vidéo sans statut valide en base de données.",
                code=ErrCode.CONTEXT,
                ctx={"video": video_path},
            )
        if vid.status in ("init",):
            logger.info("🔍 Découpage vidéo avec pyscenedetect...")
            with Timer(f"Traitement Split : {vid.name}", logger):
                try:
                    cuts = adaptive_scene_split(
                        str(video_path),
                        duration=vid.duration,
                        initial_threshold=INITIAL_THRESHOLD,
                        min_threshold=MIN_THRESHOLD,
                        threshold_step=THRESHOLD_STEP,
                        min_duration=MIN_DURATION,
                        max_duration=MAX_DURATION,
                        downscale_factor=get_downscale_factor(str(video_path)),
                    )
                except CutMindError as e:
                    logger.error("❌ Scene split error: %s", e)
                    if not Path(vid.video_path).exists():
                        logger.warning(f"⚠️ Vidéo introuvable : {vid.video_path}")
                    if vid.tags == "" or "pyscene_error" not in vid.tags:
                        vid.add_tag_vid("pyscene_error")
                    else:
                        error_path = move_to_error(file_path=Path(video_path), error_root=ERROR_DIR_SC)
                        vid.video_path = str(error_path)
                        vid.status = "error"
                        logger.info(f"🗑️ Fichier déplacé vers le dossier Error : {error_path}")
                    repo.update_video(vid)
                    raise CutMindError(
                        f"❌ Erreur lors de Découpage pyscenedetect {vid.name}",
                        code=ErrCode.UNEXPECTED,
                    ) from e

            # Création des segments SmartCut
            vid.segments = [Segment(id=i + 1, start=s, end=e) for i, (s, e) in enumerate(cuts)]
            vid.finalize_segments(OUTPUT_DIR_SC)

            for seg in vid.segments:
                logger.debug(f"seg : {seg}")
                repo._insert_segment(seg)

            vid.status = "scenes_done"
            repo.update_video(vid)
        else:
            logger.info("⏩ Étape pyscenedetect déjà effectuée — skip.")

        vid = repo.get_video_with_segments(video_id=vid.id)
        if not vid or not vid.status:
            raise CutMindError(
                f"Vidéo introuvable en base de données pour l'ID {session}",
                code=ErrCode.NOT_FOUND,
            )

        # ======================
        # 🧠 Étape 2 : Analyse IA
        # ======================
        if vid.status in ("scenes_done",):
            logger.info("🧠 Analyse IA segment par segment avec suivi de session...")

            pending_segments = vid.get_pending_segments()
            logger.debug("Segments en attente : %s", [s.id for s in pending_segments])

            if not pending_segments:
                logger.info("✅ Tous les segments ont déjà été traités par l’IA.")
                vid.status = "ia_done"
                repo.update_video(vid)
            else:
                logger.info("📊 %d segments à traiter par l’IA...", len(pending_segments))

                try:
                    run_ia_pipeline(
                        video_path=str(video_path),
                        segments=pending_segments,
                        frames_per_segment=FRAME_PER_SEGMENT,
                        auto_frames=AUTO_FRAMES,
                        base_rate=BASE_RATE,
                        fps_extract=FPS_EXTRACT,
                        lite=False,  # ou True dans le flow LITE
                        logger=logger,
                    )

                    vid.status = "ia_done"
                    repo.update_video(vid)

                except Exception as exc:  # pylint: disable=broad-except
                    if vid.tags == "" or "ia_error" not in vid.tags:
                        vid.add_tag_vid("ia_error")
                    else:
                        error_path = move_to_error(file_path=Path(video_path), error_root=ERROR_DIR_SC)
                        vid.video_path = str(error_path)
                        vid.status = "error"
                        logger.info(f"🗑️ Fichier déplacé vers le dossier Error : {error_path}")
                    repo.update_video(vid)
                    raise CutMindError(
                        f"❌ Erreur lors de l'analyse IA {vid.name}",
                        code=ErrCode.UNEXPECTED,
                    ) from exc
        else:
            logger.info("⏩ Étape IA déjà effectuée — skip.")
        # ======================
        # Étape 2.5 : confidence
        # ======================
        if vid.status == "ia_done":
            logger.info("🧠 Calcul d'un indice de confiance...")
            apply_confidence_to_session(
                session=vid,
                video_or_dir_name=video_path.name,
                model_name=settings.analyse_confidence.model_confidence,
                logger=logger,
            )

        vid = repo.get_video_with_segments(video_id=vid.id)
        if not vid or not vid.status or not vid.name:
            raise CutMindError(
                "Vidéo introuvable en base de données pour l'ID",
                code=ErrCode.NOT_FOUND,
            )

        # ======================
        # Étape 3 : merge
        # ======================
        if vid.status == "confidence_done":
            logger.info("🔗 Merge / harmonisation...")

            service_merge = MergeService(
                min_duration=MIN_DURATION,
                max_duration=MAX_DURATION,
            )
            print(f"service_merge : {service_merge}")
            merged_results = service_merge.merge(vid.segments)
            print(f"merged_results : {merged_results}")

            # vid.segments = []
            for res_merged in merged_results:
                seg = Segment(
                    id=res_merged.segment_id,
                    video_id=vid.id if vid.id else 0,
                    start=res_merged.start,
                    end=res_merged.end,
                    description=res_merged.description,
                    keywords=res_merged.keywords,
                    status="merged",
                    duration=round(res_merged.end - res_merged.start, 3),
                    confidence=res_merged.confidence,
                    merged_from=res_merged.merged_from,
                    fps=vid.fps,
                    resolution=vid.resolution,
                    codec=vid.codec,
                    bitrate=vid.bitrate,
                )
                print(f"seg : {seg}")
                seg.predict_filename(Path(OUTPUT_DIR_SC), vid.name)
                print(f"seg.predict_filename : {seg.predict_filename}")
                new_id = repo._insert_segment(seg)
                repo.insert_keywords_standalone(new_id, seg.keywords)
                for uid in seg.merged_from:
                    merged_seg = repo.get_segment_by_uid(uid)
                    if not merged_seg or not merged_seg.id:
                        raise CutMindError(
                            "Segment introuvable en base de données pour l'ID",
                            code=ErrCode.NOT_FOUND,
                        )
                    repo.delete_segment(merged_seg.id)

            vid.status = "merged"
            repo.update_video(vid)
            vid = repo.get_video_with_segments(video_id=vid.id)
            if not vid or not vid.status:
                raise CutMindError(
                    "Vidéo introuvable en base de données pour l'ID",
                    code=ErrCode.NOT_FOUND,
                )

        # ======================
        # ✂️ Étape 4 : Découpage final des segments
        # ======================
        if vid.status == "merged":
            logger.info("✂️ Cut final des segments...")

            service_cut = CutService()

            cut_requests = []
            for seg in vid.segments:
                if not seg.output_path:
                    raise CutMindError(
                        "Capteur vidéo non initialisé avant extraction des frames.",
                        code=ErrCode.CONTEXT,
                        ctx={"segment_id": seg.id},
                    )
                cut_requests.append(
                    CutRequest(
                        uid=seg.uid,
                        start=seg.start,
                        end=seg.end,
                        output_path=seg.output_path,
                    )
                )

            try:
                service_cut.cut_segments(str(video_path), cut_requests)
            except CutMindError as err:
                if vid.tags == "" or "cut_error" not in vid.tags:
                    vid.add_tag_vid("cut_error")
                else:
                    error_path = move_to_error(file_path=Path(video_path), error_root=ERROR_DIR_SC)
                    vid.video_path = str(error_path)
                    vid.status = "error"
                    logger.info(f"🗑️ Fichier déplacé vers le dossier Error : {error_path}")
                repo.update_video(vid)
                logger.error(f"Erreur durant le cut : {err}")
                raise CutMindError(
                    f"❌ Erreur lors cut Smartcut {vid.name}",
                    code=ErrCode.UNEXPECTED,
                ) from err

            # mise à jour de la session
            for seg in vid.segments:
                seg.status = "cut"
                seg.last_updated = datetime.now().isoformat()
                repo.update_segment_validation(seg)

            vid.status = "smartcut_done"
            repo.update_video(vid)
            logger.info("🎉 Tous les segments ont été coupés.")

        logger.info("───────────────────────────────")
        logger.info("🏁 Traitement terminé pour %s", video_path)
        video_trash = move_to_trash(video_path, TRASH_DIR_SC)
        vid.video_path = str(video_trash)
        repo.update_video(vid)
        purge_old_trash(TRASH_DIR_SC, days=PURGE_DAYS, logger=logger)
        return

    except CutMindError as err:
        raise err.with_context(get_step_ctx({"video_path": video_path})) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur lors du traitement Smartcut.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video_path": video_path}),
        ) from exc
