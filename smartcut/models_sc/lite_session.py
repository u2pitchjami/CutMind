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

from datetime import datetime
import json
import os
from pathlib import Path
import uuid

import cv2
from pymediainfo import MediaInfo

from shared.utils.config import JSON_STATES_DIR_SC
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from smartcut.models_sc.smartcut_model import Segment, SmartCutSession  # ton modèle actuel


class SmartCutLiteSession(SmartCutSession):
    """Version allégée de SmartCutSession pour segments déjà découpés."""

    @with_child_logger
    def __init__(self, dir_path: Path, virtual_name: str | None = None, logger: LoggerProtocol | None = None):
        logger = ensure_logger(logger, __name__)
        # ⚠️ Pas d'appel à super().__init__() pour éviter la dépendance à la vidéo mère
        self.video = f"[retro] {dir_path.name}"
        self.video_name = dir_path.name
        self.uid = str(uuid.uuid4())
        self.origin = "smartcut_lite"
        self.duration = 0.0
        self.fps = 0.0
        self.resolution = None
        self.codec = None
        self.bitrate = None
        self.filesize_mb = None
        self.created_at = datetime.now().isoformat()
        self.last_updated = datetime.now().isoformat()
        self.status = "cut"
        self.segments: list[Segment] = []
        self.errors: list[str] = []
        self.state_path = None

        self.dir_path = Path(dir_path)
        self.output_dir = JSON_STATES_DIR_SC
        self.lite_mode = True

        logger.info("💡 SmartCutLiteSession initialisée : %s", self.dir_path)

    # ============================================================
    # 🎞️ 1️⃣ Chargement des segments depuis le dossier
    # ============================================================
    @with_child_logger
    def load_segments_from_directory(self, logger: LoggerProtocol | None = None) -> None:
        """
        Crée un Segment() pour chaque fichier vidéo trouvé dans le dossier.
        """
        logger = ensure_logger(logger, __name__)
        video_files = sorted(list(self.dir_path.glob("*.mp4")) + list(self.dir_path.glob("*.mkv")))
        if not video_files:
            logger.warning("⚠️ Aucun segment trouvé dans %s", self.dir_path)
            return

        for idx, file in enumerate(video_files, start=1):
            seg = Segment(
                id=idx,
                uid=str(uuid.uuid4()),
                start=0.0,
                end=0.0,
                duration=None,
                description="",
                keywords=[],
                ai_status="pending",
                status="wait_ia",
                output_path=str(file),
            )
            seg.filename_predicted = file.name
            self.segments.append(seg)

        self.last_updated = datetime.now().isoformat()
        logger.info("📦 %d segments détectés dans %s", len(self.segments), self.dir_path)

    # ============================================================
    # 🧠 2️⃣ Enrichissement des métadonnées segment par segment
    # ============================================================
    @with_child_logger
    def enrich_segments_metadata(self, logger: LoggerProtocol | None = None) -> None:
        """
        Récupère les métadonnées techniques pour chaque segment vidéo.
        Utilise pymediainfo si disponible, sinon fallback sur OpenCV.
        """
        logger = ensure_logger(logger, __name__)
        if not self.segments:
            logger.warning("⚠️ Aucun segment à enrichir.")
            return

        for seg in self.segments:
            try:
                media_info = MediaInfo.parse(seg.output_path)
                video_track = next((t for t in media_info.tracks if t.track_type == "Video"), None)
                if video_track:
                    seg.duration = round(video_track.duration / 1000, 3) if video_track.duration else None
                    seg.fps = float(video_track.frame_rate) if video_track.frame_rate else 0.0
                    seg.resolution = f"{video_track.width}x{video_track.height}" if video_track.width else None
                    seg.codec = video_track.codec
                    seg.bitrate = int(video_track.bit_rate) if video_track.bit_rate else None
                    if seg.output_path and os.path.exists(seg.output_path):
                        seg.filesize_mb = round(os.path.getsize(seg.output_path) / (1024 * 1024), 2)
                    else:
                        seg.filesize_mb = None
                        logger.warning(f"⚠️ Fichier introuvable ou chemin vide pour {seg.uid}")
                    seg.start = 0.0
                    seg.end = seg.duration or 0.0
                else:
                    raise ValueError("Aucune piste vidéo détectée")

            except Exception as exc:  # pylint: disable=broad-except
                logger.warning(f"⚠️ pymediainfo échoué pour {seg.output_path} : {exc}")
                try:
                    if not seg.output_path or not os.path.exists(seg.output_path):
                        raise FileNotFoundError("Chemin de fichier vide ou introuvable")
                    cap = cv2.VideoCapture(seg.output_path)
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    duration = round(frame_count / fps, 3) if fps > 0 else 0.0
                    seg.fps = fps
                    seg.resolution = f"{width}x{height}"
                    seg.duration = duration
                    seg.start = 0.0
                    seg.end = duration
                    seg.codec = "unknown"
                    if seg.output_path and os.path.exists(seg.output_path):
                        seg.filesize_mb = round(os.path.getsize(seg.output_path) / (1024 * 1024), 2)
                    else:
                        seg.filesize_mb = None
                        logger.warning(f"⚠️ Fichier introuvable ou chemin vide pour {seg.uid}")
                    cap.release()
                except Exception as sub_exc:
                    logger.error(f"❌ Échec enrichissement segment {seg.output_path} : {sub_exc}")
                    seg.error = str(sub_exc)

        self.last_updated = datetime.now().isoformat()
        logger.info("🎞️ Métadonnées enrichies pour %d segments.", len(self.segments))

    # ============================================================
    # 💾 3️⃣ Sauvegarde JSON
    # ============================================================
    @with_child_logger
    def save(self, path: str | None = None, logger: LoggerProtocol | None = None) -> None:
        """
        Sauvegarde la session au format JSON SmartCut standard.
        """
        logger = ensure_logger(logger, __name__)
        path = path or str(self.output_dir / f"{self.dir_path.name}.smartcut_state.json")
        self.state_path = path
        self.output_dir.mkdir(parents=True, exist_ok=True)

        data = self.to_dict()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info("💾 Session SmartCut-Lite sauvegardée : %s", path)
