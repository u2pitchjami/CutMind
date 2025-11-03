"""
SmartCut Data Model v2
======================

Modélisation enrichie et typée du pipeline SmartCut :
- Persistance d'état JSON (écriture atomique)
- Métadonnées techniques vidéo (résolution, codec, etc.)
- Gestion d'erreurs robuste
- Compatibilité mypy / pylint
- Prédiction de noms de fichiers segments

Auteur : DevOps Assistant
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any, Literal
import uuid

import cv2
from pymediainfo import MediaInfo

from shared.utils.config import JSON_STATES_DIR_SC
from shared.utils.logger import get_logger

logger = get_logger(__name__)


# ============================================================
# 🎬 Segment Model
# ============================================================


@dataclass
class Segment:
    """
    Représente un segment vidéo analysé et enrichi.
    """

    id: int
    uid: str = field(default_factory=lambda: str(uuid.uuid4()))  # identifiant unique global
    start: float = 0.0
    end: float = 0.0
    description: str = ""
    keywords: list[str] = field(default_factory=list)
    ai_status: Literal["pending", "processing", "done", "failed"] = "pending"
    duration: float | None = None
    confidence: float | None = None
    filename_predicted: str | None = None
    output_path: str | None = None
    error: str | None = None
    merged_from: list[str] = field(default_factory=list)  # 🆕 trace les UID sources
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())

    # --- Méthodes utilitaires ---

    def compute_duration(self) -> None:
        """
        Calcule et met à jour la durée du segment.
        """
        self.duration = round(self.end - self.start, 3)

    def predict_filename(self, base_dir: str | Path = "./outputs") -> None:
        """
        Génère un nom de fichier prédictif stable et unique.

        Exemple : seg_0001_a1b2c3d4.mp4
        """
        base = Path(base_dir)
        name = f"seg_{self.id:04d}_{self.uid[:8]}.mp4"  # 🧠 unique et cohérent
        self.filename_predicted = name
        self.output_path = str(base / name)

    def to_dict(self) -> dict[str, Any]:
        """
        Convertit le segment en dictionnaire JSON-compatible.
        """
        return dict(vars(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Segment:
        """
        Recrée un segment à partir d'un dictionnaire JSON.

        Gère la rétrocompatibilité pour les anciens JSON sans `uid` ni `merged_from`.
        """
        if "uid" not in data:
            data["uid"] = str(uuid.uuid4())
            logger.debug("🆕 UID généré pour un ancien segment : %s", data["uid"])

        # Si 'merged_from' absent, on initialise une liste vide
        if "merged_from" not in data:
            data["merged_from"] = []

        if "last_updated" not in data:
            data["last_updated"] = datetime.now().isoformat()

        return cls(**data)


# ============================================================
# 🧠 SmartCutSession Model
# ============================================================


@dataclass
class SmartCutSession:
    """
    Modèle global enrichi pour le suivi complet d'une session SmartCut.
    """

    video: str
    uid: str = field(default_factory=lambda: str(uuid.uuid4()))
    duration: float = 0.0
    fps: float = 0.0
    resolution: str | None = None
    codec: str | None = None
    bitrate: int | None = None
    filesize_mb: float | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())
    status: Literal["init", "scenes_done", "ia_done", "confidence_done", "harmonized", "merged", "cut"] = "init"
    segments: list[Segment] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    state_path: str | None = None

    # ============================================================
    # 🔧 Méthodes principales
    # ============================================================

    def update_segment(self, segment_id: int, **kwargs: Any) -> None:
        """
        Met à jour un segment existant.
        """
        try:
            seg = next(s for s in self.segments if s.id == segment_id)
            for key, val in kwargs.items():
                if hasattr(seg, key):
                    setattr(seg, key, val)
            seg.compute_duration()
            self.last_updated = datetime.now().isoformat()
            logger.debug("Segment %s mis à jour : %s", segment_id, kwargs)
        except StopIteration:
            error_msg = f"Segment {segment_id} introuvable."
            self.errors.append(error_msg)
            logger.error(error_msg)

    def get_pending_segments(self) -> list[Segment]:
        """
        Retourne la liste des segments encore à traiter par l'IA.
        """
        pending = [s for s in self.segments if s.ai_status != "done"]
        logger.debug("%d segments en attente.", len(pending))
        return pending

    # ============================================================
    # 🧩 Enrichissement et finalisation
    # ============================================================

    def enrich_metadata(self) -> None:
        """
        Récupère les métadonnées techniques de la vidéo source.
        """
        try:
            media_info = MediaInfo.parse(self.video)
            for track in media_info.tracks:
                if track.track_type == "Video":
                    self.resolution = f"{track.width}x{track.height}"
                    self.codec = track.codec
                    self.bitrate = track.bit_rate
                    self.filesize_mb = round(Path(self.video).stat().st_size / (1024 * 1024), 2)
                    if not self.duration or self.duration == 0:
                        self.duration = round(track.duration / 1000, 3)
                    if not self.fps or self.fps == 0:
                        self.fps = float(track.frame_rate)
            self.last_updated = datetime.now().isoformat()
            logger.info("🎞️ Métadonnées enrichies pour %s", self.video)
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Erreur enrichissement metadata : %s", exc)
            self.errors.append(str(exc))

    def finalize_segments(self, output_dir: str | Path = "./outputs") -> None:
        """
        Calcule la durée et le nom de fichier de sortie pour chaque segment.
        """
        for seg in self.segments:
            seg.compute_duration()
            seg.predict_filename(output_dir)
        self.last_updated = datetime.now().isoformat()

    # ============================================================
    # 💾 Persistence JSON
    # ============================================================

    def to_dict(self) -> dict[str, Any]:
        """
        Convertit la session en dictionnaire JSON-compatible
        sans casser les références ni perdre les mises à jour runtime.
        """
        return {
            "video": self.video,
            "uid": self.uid,
            "duration": self.duration,
            "fps": self.fps,
            "resolution": self.resolution,
            "codec": self.codec,
            "bitrate": self.bitrate,
            "filesize_mb": self.filesize_mb,
            "created_at": self.created_at,
            "last_updated": self.last_updated,
            "status": self.status,
            "segments": [seg.to_dict() for seg in self.segments],
            "errors": self.errors,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SmartCutSession:
        segments = []
        for seg_data in data.get("segments", []):
            if isinstance(seg_data, Segment):
                segments.append(seg_data)
            else:
                segments.append(Segment(**seg_data))
        data = {**data, "segments": segments}
        return cls(**data)

    def save(self, path: str | None = None) -> None:
        """
        Sauvegarde la session dans un fichier JSON (écriture atomique + flush disque).
        """
        if not path:
            path = self.state_path or self._default_path()
        logger.debug(f"💾 Sauvegarde vers: {path}")

        try:
            tmp_path = f"{path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as file:
                json.dump(self.to_dict(), file, indent=2, ensure_ascii=False)
                file.flush()
                os.fsync(file.fileno())

            os.replace(tmp_path, path)

            try:
                os.sync()
            except AttributeError:
                pass

            try:
                os.system("sync")
            except Exception as e:
                logger.debug(f"Sync système échouée : {e}")

            logger.info("💾 Session sauvegardée dans %s", path)

        except Exception as exc:  # pylint: disable=broad-except
            backup_path = f"{path}.bak"
            logger.error("❌ Erreur de sauvegarde : %s", exc)
            try:
                with open(backup_path, "w", encoding="utf-8") as bak:
                    json.dump(self.to_dict(), bak, indent=2, ensure_ascii=False)
                    bak.flush()
                    os.fsync(bak.fileno())
                logger.warning("⚠️ Backup sauvegardé dans %s", backup_path)
            except Exception as bak_exc:  # pylint: disable=broad-except
                logger.error("❌ Impossible d'écrire le backup : %s", bak_exc)

    @classmethod
    def load(cls, path: str) -> SmartCutSession | None:
        """
        Charge une session à partir d'un fichier JSON.
        """
        try:
            with open(path, encoding="utf-8") as file:
                data: dict[str, Any] = json.load(file)

            segments = []
            for seg in data.get("segments", []):
                kws = seg.get("keywords")
                if isinstance(kws, str):
                    seg["keywords"] = [kw.strip() for kw in kws.split(",") if kw.strip()]

                # 🧠 Normalisation description
                if "description" not in seg or seg["description"] is None:
                    seg["description"] = ""

                segments.append(Segment(**seg))

            return cls(
                video=data["video"],
                duration=data.get("duration", 0.0),
                fps=data.get("fps", 0.0),
                resolution=data.get("resolution"),
                codec=data.get("codec"),
                bitrate=data.get("bitrate"),
                filesize_mb=data.get("filesize_mb"),
                created_at=data.get("created_at", datetime.now().isoformat()),
                last_updated=data.get("last_updated", datetime.now().isoformat()),
                status=data.get("status", "init"),
                segments=segments,
                errors=data.get("errors", []),
            )
        except FileNotFoundError:
            logger.warning("Aucune session trouvée à %s", path)
            return None
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Erreur de chargement du fichier JSON : %s", exc)
            return None

    def _default_path(self) -> str:
        """
        Construit un chemin par défaut pour le fichier JSON.
        """
        base_name = os.path.splitext(os.path.basename(self.video))[0]
        return f"{base_name}.smartcut_state.json"

    def init_from_video(self, video_path: str | None = None) -> None:
        """
        Initialise la durée et les FPS à partir du fichier vidéo.
        """
        path = video_path or self.video
        try:
            cap = cv2.VideoCapture(path)
            if not cap.isOpened():
                raise ValueError(f"Impossible d'ouvrir la vidéo : {path}")

            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            duration = frame_count / fps if fps > 0 else 0.0

            self.fps = round(fps, 3)
            self.duration = round(duration, 3)
            self.last_updated = datetime.now().isoformat()

            cap.release()
            logger.info("Durée/FPS initialisés pour %s : %.2fs @ %.2f FPS", path, duration, fps)
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Erreur d'initialisation vidéo : %s", exc)
            self.errors.append(str(exc))

    # ============================================================
    # 🚀 Méthode d'initialisation complète (bootstrap)
    # ============================================================

    @classmethod
    def bootstrap_session(cls, video_path: str | Path, out_dir: str | Path) -> SmartCutSession:
        """
        Initialise ou recharge automatiquement une session SmartCut.

        Étapes : 1️⃣ Charge une session existante si le JSON est présent 2️⃣ Sinon crée une nouvelle session et
        initialise la vidéo 3️⃣ Enrichit les métadonnées techniques (durée, FPS, codec, résolution, etc.) 4️⃣ Finalise
        les segments s'ils existent 5️⃣ Sauvegarde la session enrichie et renvoie l'objet prêt

        Cette méthode garantit que la session est toujours exploitable, même après un crash ou un redémarrage.
        """
        video_path = Path(video_path)
        out_dir = Path(out_dir)
        state_path = JSON_STATES_DIR_SC / f"{video_path.stem}.smartcut_state.json"

        # ♻️ Tentative de reprise de session existante
        session = cls.load(str(state_path))
        if session:
            session.state_path = str(state_path)
            logger.info("♻️ Reprise de session existante : %s", session.status)
            # Enrichissement si nécessaire
            if not session.resolution or session.fps == 0:
                session.enrich_metadata()
                session.save(str(state_path))
                logger.info("🔁 Métadonnées vidéo complétées pour la session.")
            return session
        else:
            session = cls(video=str(video_path), state_path=str(state_path))

        # ✨ Nouvelle session SmartCut
        logger.info("✨ Nouvelle session SmartCut : %s", video_path)
        session = cls(video=str(video_path))

        # 🧠 Extraction de la durée / FPS via OpenCV
        session.init_from_video(str(video_path))

        # 🎞️ Enrichissement des métadonnées techniques
        session.enrich_metadata()

        if not getattr(session, "uid", None):
            session.uid = str(uuid.uuid4())

        # 🏷️ Préparation des segments si déjà connus
        if session.segments:
            session.finalize_segments(out_dir / "outputs")

        # 💾 Sauvegarde initiale
        session.save(str(state_path))
        logger.info("💾 Session SmartCut créée et enregistrée à %s", state_path)

        return session
