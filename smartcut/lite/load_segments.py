"""
SmartCutLiteSession
===================
Version simplifiée du modèle SmartCutSession pour les cas où
aucune vidéo d'origine n'est disponible (segments déjà coupés).

💡 Fonctionnalités :
- Charge automatiquement les fichiers vidéo d’un dossier
- Calcule les métadonnées techniques pour chaque segment
- Génère un JSON SmartCut standard (CutMind compatible)
"""

from __future__ import annotations

from pathlib import Path
import uuid

from cutmind.db.repository import CutMindRepository
from cutmind.models_cm.db_models import Segment, Video
from shared.models.exceptions import CutMindError, ErrCode
from shared.services.video_preparation import prepare_video
from shared.utils.logger import LoggerProtocol, ensure_logger


def load_segments_from_directory(video: Video, directory_path: Path, logger: LoggerProtocol | None = None) -> None:
    """
    Crée un Segment() pour chaque fichier vidéo du dossier,
    en passant chaque fichier par prepare_video() pour normalisation + métadonnées.
    """
    logger = ensure_logger(logger, __name__)
    repo = CutMindRepository()
    # on accepte plus d’extensions (mp4, mkv, mov, etc.)
    exts = (".mp4", ".mkv", ".mov", ".avi")
    video_files = sorted(f for f in directory_path.iterdir() if f.is_file() and f.suffix.lower() in exts)

    if not video_files:
        logger.warning("⚠️ Aucun segment vidéo trouvé dans %s", directory_path)
        return

    segments = []
    errors = []
    if not video or not video.id:
        raise CutMindError(
            "Vidéo invalide ou non insérée en base avant le chargement des segments.",
            code=ErrCode.NOT_FOUND,
            ctx={"dir": str(directory_path)},
        )

    for _, file_path in enumerate(video_files, start=1):
        try:
            prepared = prepare_video(file_path)
        except CutMindError as exc:
            # E3 : on continue, mais on enregistre l’erreur
            msg = f"Erreur préparation segment {file_path.name}: {exc}"
            logger.error(msg)
            errors.append(msg)
            continue

        seg = Segment(
            uid=str(uuid.uuid4()),
            video_id=video.id,
            start=0.0,
            end=prepared.duration,
            duration=prepared.duration,
            description="",
            status="raw",
            fps=prepared.fps,
            nb_frames=prepared.nb_frames,
            resolution=prepared.resolution,
            codec=prepared.codec,
            bitrate=prepared.bitrate,
            filesize_mb=prepared.filesize_mb,
            has_audio=prepared.has_audio,
            audio_codec=prepared.audio_codec,
            sample_rate=prepared.sample_rate,
            channels=prepared.channels,
            audio_duration=prepared.audio_duration,
            output_path=str(prepared.path),
        )
        seg.filename_predicted = Path(prepared.path).name
        repo._insert_segment(seg)
        segments.append(seg)

    logger.info("📦 %d segments prêts (après prepare_video) dans %s", len(segments), directory_path)

    if not segments:
        # aucun segment exploitable → on peut décider de lever une erreur globale
        raise CutMindError(
            "Aucun segment exploitable après préparation.",
            code=ErrCode.FILE_ERROR,  # ou un ErrCode plus spécifique si tu en ajoutes
            ctx={"dir": str(directory_path)},
        )
