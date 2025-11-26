from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any, Literal
import uuid

from shared.models.exceptions import CutMindError, ErrCode

# ============================================================
# 🎬 Segment Model
# ============================================================


@dataclass
class Segment:
    """
    Représente un segment vidéo analysé et enrichi.
    """

    id: int
    uid: str = field(default_factory=lambda: str(uuid.uuid4()))
    start: float = 0.0
    end: float = 0.0
    description: str = ""
    keywords: list[str] = field(default_factory=list)
    ai_status: Literal["pending", "processing", "done", "failed"] = "pending"
    status: str = "analyse_pyscenedetect"
    duration: float | None = None
    fps: float = 0.0
    resolution: str | None = None
    codec: str | None = None
    bitrate: int | None = None
    filesize_mb: float | None = None
    confidence: float | None = None
    filename_predicted: str | None = None
    ai_model: str | None = None
    output_path: str | None = None
    error: str | None = None
    merged_from: list[str] = field(default_factory=list)
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())

    def compute_duration(self) -> None:
        """Calcule et met à jour la durée du segment."""
        self.duration = round(self.end - self.start, 3)
        self.last_updated = datetime.now().isoformat()

    def predict_filename(self, base_dir: str | Path = "./outputs", folder_name: str = "folder") -> None:
        """
        Génère un nom de fichier prédictif stable et unique.
        Exemple : seg_0001_a1b2c3d4.mp4
        """
        base = Path(base_dir) / folder_name
        base.mkdir(parents=True, exist_ok=True)
        name = f"seg_{self.id:04d}_{self.uid}.mp4"
        self.filename_predicted = name
        self.output_path = str(base / name)
        self.last_updated = datetime.now().isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Convertit le segment en dict JSON-compatible."""
        return dict(vars(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Segment:
        """
        Recrée un segment à partir d'un dict JSON.
        Gère la rétrocompatibilité pour anciens JSON.
        """
        if "uid" not in data:
            data["uid"] = str(uuid.uuid4())
        if "merged_from" not in data:
            data["merged_from"] = []
        if "last_updated" not in data:
            data["last_updated"] = datetime.now().isoformat()
        if "keywords" in data and isinstance(data["keywords"], str):
            # vieux JSON: "kw1, kw2"
            data["keywords"] = [kw.strip() for kw in data["keywords"].split(",") if kw.strip()]
        if "description" not in data or data["description"] is None:
            data["description"] = ""
        return cls(**data)


# ============================================================
# 🧠 SmartCutSession Model (V3 simplifiée)
# ============================================================


StatusType = Literal[
    "init", "scenes_done", "ia_done", "confidence_done", "harmonized", "merged", "cut", "smartcut_done"
]


@dataclass
class SmartCutSession:
    """
    Modèle global d'une session SmartCut.

    ⚠️ V3 simplifiée :
    - Ne parle plus à ffmpeg / MediaInfo / OpenCV
    - Ne fait plus de conversion
    - Ne gère plus les métadonnées techniques directement
    - Se contente de stocker l'état et de gérer la persistance JSON
    """

    video: str
    video_name: str | None = None
    uid: str = field(default_factory=lambda: str(uuid.uuid4()))
    origin: str = "smartcut"
    duration: float = 0.0
    fps: float = 0.0
    resolution: str | None = None
    codec: str | None = None
    bitrate: int | None = None
    filesize_mb: float | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())
    status: StatusType = "init"
    segments: list[Segment] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    state_path: str | None = None

    # ---------------- Métier léger ----------------

    def update_segment(self, segment_id: int, **kwargs: Any) -> None:
        """Met à jour un segment existant (sans log)."""
        try:
            seg = next(s for s in self.segments if s.id == segment_id)
        except StopIteration as exc:
            msg = f"Segment {segment_id} introuvable."
            self.errors.append(msg)
            self.last_updated = datetime.now().isoformat()
            raise CutMindError(msg, code=ErrCode.CONTEXT, ctx={"segment_id": segment_id}) from exc

        for key, val in kwargs.items():
            if hasattr(seg, key):
                setattr(seg, key, val)
        seg.compute_duration()
        self.last_updated = datetime.now().isoformat()

    def get_pending_segments(self) -> list[Segment]:
        """Retourne les segments non traités par l'IA."""
        return [s for s in self.segments if s.ai_status != "done"]

    def finalize_segments(self, output_dir: str | Path = "./outputs") -> None:
        """
        Calcule la durée et le nom de fichier de sortie pour chaque segment.
        """
        folder_name = self.video_name or Path(self.video).stem
        for seg in self.segments:
            seg.compute_duration()
            seg.predict_filename(output_dir, folder_name)
        self.last_updated = datetime.now().isoformat()

    # ---------------- Persistance JSON ----------------

    def to_dict(self) -> dict[str, Any]:
        """Convertit la session en dict JSON-compatible."""
        return {
            "video": self.video,
            "video_name": self.video_name,
            "uid": self.uid,
            "origin": self.origin,
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
        """Construit une session à partir d'un dict JSON."""
        raw_segments = data.get("segments", [])
        segments: list[Segment] = []
        for seg_data in raw_segments:
            if isinstance(seg_data, Segment):
                segments.append(seg_data)
            else:
                segments.append(Segment.from_dict(seg_data))

        return cls(
            video=data["video"],
            video_name=data.get("video_name", Path(data["video"]).name),
            uid=data.get("uid", str(uuid.uuid4())),
            origin=data.get("origin", "smartcut"),
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
            state_path=data.get("state_path"),
        )

    def _default_path(self) -> str:
        """Construit un chemin JSON par défaut."""
        base_name = os.path.splitext(os.path.basename(self.video))[0]
        return f"{base_name}.smartcut_state.json"

    def save(self, path: str | None = None) -> None:
        """
        Sauvegarde la session dans un fichier JSON (écriture atomique).
        Lève CutmindError en cas d'échec.
        """
        final_path = path or self.state_path or self._default_path()
        tmp_path = f"{final_path}.tmp"

        try:
            data = self.to_dict()
            with open(tmp_path, "w", encoding="utf-8") as file:
                json.dump(data, file, indent=2, ensure_ascii=False)
                file.flush()
                os.fsync(file.fileno())
            os.replace(tmp_path, final_path)
            self.state_path = final_path
            self.last_updated = datetime.now().isoformat()
        except Exception as exc:  # pylint: disable=broad-except
            # On tente de nettoyer le tmp si présent
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass

            raise CutMindError(
                "Erreur lors de la sauvegarde de la session SmartCut.",
                code=ErrCode.FILEERROR,
                ctx={"path": final_path},
            ) from exc

    @classmethod
    def load(cls, path: str) -> SmartCutSession | None:
        """
        Charge une session à partir d'un fichier JSON.

        Retourne :
        - SmartCutSession si le fichier existe et est lisible
        - None si le fichier n'existe pas
        - Lève CutmindError si le JSON est corrompu ou illisible
        """
        json_path = Path(path)
        if not json_path.exists():
            return None

        try:
            with open(json_path, encoding="utf-8") as file:
                data: dict[str, Any] = json.load(file)
        except json.JSONDecodeError as exc:
            raise CutMindError(
                "JSON de session SmartCut corrompu.",
                code=ErrCode.FILEERROR,
                ctx={"path": str(json_path)},
            ) from exc
        except Exception as exc:  # pylint: disable=broad-except
            raise CutMindError(
                "Erreur lors du chargement de la session SmartCut.",
                code=ErrCode.FILEERROR,
                ctx={"path": str(json_path)},
            ) from exc

        session = cls.from_dict(data)
        session.state_path = str(json_path)
        return session
