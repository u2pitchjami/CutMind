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
from cutmind.executors.check.processing_checks import evaluate_scene_detection_output
from cutmind.executors.check.processing_log import processing_step
from cutmind.models_cm.db_models import Segment, Video
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.services.video_preparation import prepare_video
from shared.status_orchestrator.statuses import OrchestratorStatus
from shared.utils.config import ERROR_DIR_SC, OUTPUT_DIR_SC, TRASH_DIR_SC
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from shared.utils.settings import get_settings
from shared.utils.trash import move_to_trash, purge_old_trash
from smartcut.executors.split_utils import get_downscale_factor, move_to_error
from smartcut.services.cut_service import CutRequest, CutService
from smartcut.services.scene_split.pipeline_service import adaptive_scene_split


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
    settings = get_settings()

    PURGE_DAYS = settings.smartcut.purge_days
    INITIAL_THRESHOLD = settings.smartcut.initial_threshold
    MIN_THRESHOLD = settings.smartcut.min_threshold
    THRESHOLD_STEP = settings.smartcut.threshold_step
    MIN_DURATION = settings.smartcut.min_duration
    MAX_DURATION = settings.smartcut.max_duration
    logger = ensure_logger(logger, __name__)

    # ======================
    # 🧠 Étape 0 : Init session
    # ======================

    repo = CutMindRepository()

    try:
        session = repo.video_exists_by_video_path(str(video_path))

        if not session:
            # 1. Prépare la vidéo (format, durée, fps, etc.)
            prep = prepare_video(video_path, normalize=True)
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
                status=OrchestratorStatus.VIDEO_INIT,
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
        if vid.status in (OrchestratorStatus.VIDEO_READY_PYSCENE,):
            logger.info("🔍 Découpage vidéo avec pyscenedetect...")
            with processing_step(vid, None, action="Découpage pyscenedetect") as history:
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
                    status, message = evaluate_scene_detection_output(True, len(cuts))
                    history.status = status
                    history.message = message
                except CutMindError as e:
                    logger.error("❌ Scene split error: %s", e)
                    if not Path(vid.video_path).exists():
                        logger.warning(f"⚠️ Vidéo introuvable : {vid.video_path}")
                    if vid.tags == "" or "pyscene_error" not in vid.tags:
                        vid.add_tag_vid("pyscene_error")
                    else:
                        error_path = move_to_error(file_path=Path(video_path), error_root=ERROR_DIR_SC)
                        vid.video_path = str(error_path)
                        vid.status = OrchestratorStatus.VIDEO_SMARTCUT_ERROR
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

            vid.status = OrchestratorStatus.VIDEO_PYSCENE_DONE
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
        # ✂️ Étape 4 : Découpage final des segments
        # ======================
        if vid.status == OrchestratorStatus.VIDEO_READY_FOR_CUT:
            logger.info("✂️ Cut final des segments...")

            service_cut = CutService()

            cut_requests = []
            for seg in vid.segments:
                if not vid.id or not seg.id or not seg.output_path:
                    raise CutMindError(
                        "Capteur vidéo non initialisé avant extraction des frames.",
                        code=ErrCode.CONTEXT,
                        ctx={"segment_id": seg.id},
                    )
                cut_requests.append(
                    CutRequest(
                        seg_obj=seg,
                        uid=seg.uid,
                        start=seg.start,
                        end=seg.end,
                        output_path=seg.output_path,
                    )
                )

            try:
                service_cut.cut_segments(vid, str(video_path), cut_requests)
            except CutMindError as err:
                if vid.tags == "" or "cut_error" not in vid.tags:
                    vid.add_tag_vid("cut_error")
                else:
                    error_path = move_to_error(file_path=Path(video_path), error_root=ERROR_DIR_SC)
                    vid.video_path = str(error_path)
                    vid.status = OrchestratorStatus.VIDEO_SMARTCUT_ERROR
                    logger.info(f"🗑️ Fichier déplacé vers le dossier Error : {error_path}")
                repo.update_video(vid)
                logger.error(f"Erreur durant le cut : {err}")
                raise CutMindError(
                    f"❌ Erreur lors cut Smartcut {vid.name}",
                    code=ErrCode.UNEXPECTED,
                ) from err

            # mise à jour de la session
            for seg in vid.segments:
                seg.status = OrchestratorStatus.SEGMENT_CUT_DONE
                seg.pipeline_target = OrchestratorStatus.SEGMENT_IN_CUT_VALIDATION
                seg.last_updated = datetime.now().isoformat()
                repo.update_segment_validation(seg)

            vid.status = OrchestratorStatus.VIDEO_CUT_DONE
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
        logger.exception("💥 Erreur Smartcut")
        raise err.with_context(get_step_ctx({"video_path": video_path})) from err
    except Exception as exc:
        logger.exception("💥 Erreur Smartcut")
        raise CutMindError(
            "❌ Erreur lors du traitement Smartcut.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video_path": video_path}),
            original_exception=exc,
        ) from exc
