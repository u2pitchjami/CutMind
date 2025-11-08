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

from shared.models.config_manager import CONFIG
from shared.utils.config import JSON_STATES_DIR_SC, TRASH_DIR_SC
from shared.utils.logger import get_logger
from shared.utils.safe_runner import safe_main
from shared.utils.trash import move_to_trash, purge_old_trash
from smartcut.analyze.analyze_confidence import compute_confidence
from smartcut.analyze.analyze_utils import extract_keywords_from_filename
from smartcut.analyze.main_analyze import analyze_video_segments
from smartcut.ffsmartcut.ffsmartcut import cut_video, ensure_safe_video_format, get_duration
from smartcut.merge.merge_main import process_result
from smartcut.models_sc.smartcut_model import Segment, SmartCutSession
from smartcut.scene_split.main_scene_split import adaptive_scene_split

logger = get_logger(__name__)

PURGE_DAYS = CONFIG.smartcut["smartcut"]["purge_days"]
USE_CUDA = CONFIG.smartcut["smartcut"]["use_cuda"]
SEED = CONFIG.smartcut["smartcut"]["seed"]

INITIAL_THRESHOLD = CONFIG.smartcut["smartcut"]["initial_threshold"]
MIN_THRESHOLD = CONFIG.smartcut["smartcut"]["min_threshold"]
THRESHOLD_STEP = CONFIG.smartcut["smartcut"]["threshold_step"]
MIN_DURATION = CONFIG.smartcut["smartcut"]["min_duration"]
MAX_DURATION = CONFIG.smartcut["smartcut"]["max_duration"]

FRAME_PER_SEGMENT = CONFIG.smartcut["smartcut"]["frame_per_segment"]
AUTO_FRAMES = CONFIG.smartcut["smartcut"]["auto_frames"]

VCODEC_CPU = CONFIG.smartcut["smartcut"]["vcodec_cpu"]
VCODEC_GPU = CONFIG.smartcut["smartcut"]["vcodec_gpu"]
CRF = CONFIG.smartcut["smartcut"]["crf"]
PRESET_CPU = CONFIG.smartcut["smartcut"]["preset_cpu"]
PRESET_GPU = CONFIG.smartcut["smartcut"]["preset_gpu"]


@safe_main
def multi_stage_cut(
    video_path: Path,
    out_dir: Path,
    use_cuda: bool = False,
    seed: int | None = None,
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
    out_dir.mkdir(parents=True, exist_ok=True)

    # 🧩 Normalisation du format vidéo dès le départ
    safe_path = ensure_safe_video_format(str(video_path))
    if safe_path != str(video_path):
        logger.info(f"🎞️ Conversion automatique : {video_path.name} → {Path(safe_path).name}")
        move_to_trash(video_path, TRASH_DIR_SC)
        video_path = Path(safe_path)

    duration = get_duration(video_path)
    if duration <= 0:
        logger.error("Durée inconnue pour %s", video_path)
        return

    # ======================
    # 🧠 Étape 0 : Init session
    # ======================
    duration = get_duration(video_path)
    if duration <= 0:
        logger.error("Durée inconnue pour %s", video_path)
        return

    state_path = JSON_STATES_DIR_SC / f"{video_path.stem}.smartcut_state.json"
    session = SmartCutSession.load(str(state_path))

    if not session:
        session = SmartCutSession.bootstrap_session(video_path, out_dir)
        logger.info("✅ Session prête : %s (%.2fs @ %.2f FPS)", session.status, session.duration, session.fps)
    else:
        logger.info("♻️ Reprise de session existante : %s", session.status)
        # Optionnel : enrichir à nouveau si des infos manquent
        if not session.resolution or session.fps == 0:
            session.enrich_metadata()
            session.save(str(state_path))
            logger.info("🔁 Métadonnées complétées pour la session existante.")

    # ======================
    # 🎬 Étape 1 : Découpage pyscenedetect
    # ======================
    if session.status in ("init",):
        logger.info("🔍 Découpage vidéo avec pyscenedetect...")
        cuts = adaptive_scene_split(
            str(video_path),
            initial_threshold=INITIAL_THRESHOLD,
            min_threshold=MIN_THRESHOLD,
            threshold_step=THRESHOLD_STEP,
            min_duration=MIN_DURATION,
            max_duration=MAX_DURATION,
        )
        logger.info("🎞️ %d coupures détectées.", len(cuts))

        # Création des segments
        session.segments = [Segment(id=i + 1, start=s, end=e) for i, (s, e) in enumerate(cuts)]
        for seg in session.segments:
            seg.compute_duration()

        session.status = "scenes_done"
        session.save(str(state_path))
    else:
        logger.info("⏩ Étape pyscenedetect déjà effectuée — skip.")

    # ======================
    # 🧠 Étape 2 : Analyse IA (avec SmartCutSession)
    # ======================
    if session.status in ("scenes_done",):
        logger.info("🧠 Analyse IA segment par segment avec suivi de session...")

        # On ne traite que les segments dont le statut n’est pas "done"
        pending_segments = session.get_pending_segments()
        logger.debug(f"Segments en attente : {[s.id for s in pending_segments]}")
        if not pending_segments:
            logger.info("✅ Tous les segments ont déjà été traités par l’IA.")
            session.status = "ia_done"
            session.save(str(state_path))
        else:
            logger.info(f"📊 {len(pending_segments)} segments à traiter par l’IA...")
            cuts = [(seg.start, seg.end) for seg in pending_segments]

            try:
                # Appel à ta fonction d’analyse — le suivi JSON se fait à l’intérieur
                analyze_video_segments(
                    video_path=str(video_path),
                    frames_per_segment=FRAME_PER_SEGMENT,
                    auto_frames=AUTO_FRAMES,
                    session=session,
                )

                # Par sécurité, on s’assure que le statut soit mis à jour
                if all(s.ai_status == "done" for s in session.segments):
                    session.status = "ia_done"
                else:
                    logger.warning("🚧 Certains segments IA n’ont pas été traités complètement.")
                session.save(str(state_path))

            except Exception as exc:  # pylint: disable=broad-except
                logger.error("💥 Erreur pendant l’analyse IA : %s", exc)
                session.errors.append(str(exc))
                session.save(str(state_path))
                raise
    else:
        logger.info("⏩ Étape IA déjà effectuée — skip.")
    # ======================
    # 🪄 Étape 2.5 : confidence
    # ======================
    if session.status in ("ia_done",):
        logger.info("🧠 Calcul d'un indice de confiance :")
        try:
            auto_keywords = extract_keywords_from_filename(video_path.name)
            for seg in session.segments:
                if seg.ai_status == "done":
                    seg.confidence = compute_confidence(seg.description, seg.keywords)
                    seg.last_updated = datetime.now().isoformat()
                    seg.status = "confidence_done"
                    logger.info(f"  - Segment {seg.id}: confidence = {seg.confidence:.3f}")
                    if seg.keywords:
                        merged = set(seg.keywords + auto_keywords)
                        seg.keywords = list(merged)
                    else:
                        seg.keywords = auto_keywords.copy()

                    logger.debug(f"🏷️ Seg {seg.uid}: keywords enrichis → {seg.keywords}")
                    session.save(str(state_path))

            if all(s.confidence != "null" for s in session.segments):
                session.status = "confidence_done"
            else:
                logger.warning("🚧 Certains segments confidence n’ont pas été traités complètement.")
            session.save(str(state_path))

        except Exception as exc:  # pylint: disable=broad-except
            logger.error("💥 Erreur pendant le calcul de l'indice de confiance : %s", exc)
            session.errors.append(str(exc))
            session.save(str(state_path))
            raise
    else:
        logger.info("⏩ Étape confidence déjà effectuée — skip.")

    # ======================
    # 🪄 Étape 3 : Harmonisation / Merge des segments
    # ======================
    if session.status in ("confidence_done",):
        logger.info("🔗 Harmonisation et fusion des segments...")
        wrong_segments = [s for s in session.segments if isinstance(s.keywords, str)]
        if wrong_segments:
            logger.warning(f"⚠️ {len(wrong_segments)} segments ont des keywords mal typés (str au lieu de list[str]) !")

        try:
            # Préparation du format attendu par process_result
            result_session = SmartCutSession(
                video=str(video_path),
                segments=session.segments,
            )
            logger.debug(f"📦 Segments à envoyer dans process_result ({len(session.segments)} segments):")
            for i, seg in enumerate(session.segments):
                logger.debug(
                    f"  [{i}] ID: {seg.id}, "
                    f"start: {seg.start:.2f}, end: {seg.end:.2f}, "
                    f"type(keywords): {type(seg.keywords)}, "
                    f"keywords: {seg.keywords}"
                )

            merged_result: SmartCutSession = process_result(
                result_session,
                min_duration=MIN_DURATION,
                max_duration=MAX_DURATION,
            )

            # 🔁 Mise à jour des segments fusionnés (si applicable)
            if merged_result.segments:
                session.segments = []
                for i, seg in enumerate(merged_result.segments, start=1):
                    new_seg = Segment(
                        id=i,
                        start=seg.start,
                        end=seg.end,
                        description=seg.description,
                        keywords=list(seg.keywords),
                        ai_status="done",
                        status="merged",
                        duration=seg.duration if seg.duration else round(seg.end - seg.start, 3),
                        confidence=seg.confidence,
                        merged_from=getattr(seg, "merged_from", []),
                    )

                    # 🧠 Conserve l’UID du segment fusionné si déjà défini, sinon nouveau
                    new_seg.uid = getattr(seg, "uid", str(uuid.uuid4()))

                    # 🧾 Recalcule un nom de fichier prédictif propre
                    new_seg.predict_filename(Path("/basedir/smart_cut/outputs/"))

                    session.segments.append(new_seg)

                session.status = "merged"
                session.last_updated = datetime.now().isoformat()
                session.save(str(state_path))
                logger.info("💾 Segments fusionnés mis à jour et sauvegardés dans le JSON.")

                logger.info(f"✅ Merge effectué : {len(session.segments)} segments après harmonisation.")
            else:
                logger.warning("⚠️ Aucun segment résultant du merge. Structure inchangée.")

            session.status = "harmonized"
            session.save(str(state_path))

        except Exception as exc:  # pylint: disable=broad-except
            logger.error("💥 Erreur pendant le merge/harmonisation : %s", exc)
            session.errors.append(str(exc))
            session.save(str(state_path))
            raise
    else:
        logger.info("⏩ Étape merge déjà effectuée — skip.")

    # ======================
    # ✂️ Étape 4 : Découpage final des segments
    # ======================
    if session.status in ("harmonized",):
        logger.info("✂️ Export final des segments vidéo...")
        # logger.debug(f"Session ({session}):")
        outputs: list[Path] = []
        try:
            for i, seg in enumerate(session.segments, 1):
                start, end = seg.start, seg.end
                keywords = ", ".join(seg.keywords) if isinstance(seg.keywords, list) else str(seg.keywords)

                try:
                    res = cut_video(
                        video_path=video_path,
                        start=start,
                        end=end,
                        out_dir=out_dir,
                        index=i,
                        keywords=keywords,
                        use_cuda=use_cuda,
                        vcodec_cpu=VCODEC_CPU,
                        vcodec_gpu=VCODEC_GPU,
                        crf=CRF,
                        preset_cpu=PRESET_CPU,
                        preset_gpu=PRESET_GPU,
                        session=session,
                        state_path=state_path,
                    )

                    if res:
                        outputs.append(res)
                        logger.info(f"{i:02d}. [{start:6.1f}s → {end:6.1f}s] → {keywords}")
                    else:
                        raise RuntimeError("cut_video() n’a rien renvoyé.")

                except Exception as seg_exc:  # pylint: disable=broad-except
                    seg.error = str(seg_exc)
                    seg.ai_status = "failed"
                    session.errors.append(str(seg_exc))
                    logger.warning(f"⚠️ Erreur sur le segment {i}: {seg_exc}")
                    session.save(str(state_path))
                    raise

            # Marquer la fin du traitement global
            session.status = "smartcut_done"
            session.save(str(state_path))
            logger.info("✅ %d segments exportés → %s", len(outputs), out_dir)

        except Exception as exc:  # pylint: disable=broad-except
            logger.error("💥 Erreur générale pendant le découpage final : %s", exc)
            session.errors.append(str(exc))
            session.save(str(state_path))
            raise
    else:
        logger.info("⏩ Étape cut déjà effectuée — skip.")

    logger.info("───────────────────────────────")
    logger.info("🏁 Traitement terminé pour %s", video_path)
    move_to_trash(video_path, TRASH_DIR_SC)
    purge_old_trash(TRASH_DIR_SC, days=PURGE_DAYS)
    return
