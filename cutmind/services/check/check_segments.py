"""
RouterWorker
============

Envoie automatiquement les segments 'validated' mais hors standard
(résolution < 1080p ou fps != 60) vers ComfyUI-Router.

- Sélectionne les vidéos concernées
- Copie les fichiers dans le répertoire d'import de Router
- Met à jour les statuts dans la base (segments + vidéos)
"""

from pathlib import Path

from cutmind.executors.check.processing_log import processing_step
from cutmind.executors.check.segments import inspect_video, is_video_compliant
from cutmind.models_cm.db_models import Segment, Video
from cutmind.process.file_mover import FileMover
from shared.executors.ffmpeg_convert import convert_safe_video_format
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.models.timer_manager import Timer
from shared.utils.config import WORKDIR_CM
from shared.utils.logger import LoggerProtocol, ensure_logger


class CheckSegments:
    """Gère l'envoi automatique des segments non conformes vers ComfyUI Router."""

    def __init__(self, vid: Video, segments: list[Segment], logger: LoggerProtocol | None = None):
        self.logger = ensure_logger(logger, __name__)
        self.video = vid
        self.segments = segments
        self.file_mover = FileMover()

    # ---------------------------------------------------------
    # 🚀 Main Entry Point
    # ---------------------------------------------------------
    def run(self) -> int:
        """
        Exécute un cycle complet d'envoi vers Router.
        Retourne le nombre total de segments envoyés pour traitement.
        """

        self.logger.info("🚀 Démarrage Check Segments")
        if not self.video:
            self.logger.warning("⚠️ Vidéo introuvable")
            return 0

        processed_count = 0

        self.logger.info("🎞️ Vidéo '%s' nb segments: %i", self.video.name, len(self.segments))

        # 3️⃣ Transaction : copie + maj DB
        with Timer(f"Traitement Comfyui pour la vidéo : {self.video.name}", self.logger):
            try:
                # delete_files(path=INPUT_DIR, ext="*.mp4")

                for seg in self.segments:
                    with processing_step(self.video, seg, action="Check Segments"):
                        if not seg.output_path:
                            raise Exception("Impossible de récupérer le segment.")

                        with Timer(f"Traitement du segment : {seg.filename_predicted}", self.logger):
                            metadata = inspect_video(Path(seg.output_path))

                            if is_video_compliant(metadata):
                                self.logger.info(f"Video {seg.filename_predicted} est conforme.")
                                continue

                            self.logger.info(f"Video {seg.filename_predicted} n'est pas conforme.")
                            dst: Path = Path(WORKDIR_CM) / f"{seg.filename_predicted}.mp4"
                            self.file_mover.safe_copy(Path(seg.output_path), dst)
                            self.logger.info(f"Video {seg.filename_predicted} copiée vers {dst}")

                            temp_path = dst.with_suffix(".normalized.mp4")
                            convert_safe_video_format(str(dst), str(temp_path))
                            self.logger.info(f"Video {seg.filename_predicted} normalisée.")
                            dst.unlink()

                            try:
                                self.logger.debug(
                                    "appel safe_replace : final_output=%s, target_path=%s", temp_path, seg.output_path
                                )
                                FileMover.safe_replace(temp_path, Path(seg.output_path), self.logger)
                                self.logger.info(
                                    "📦 Fichier remplacé (via safe_copy) : %s → %s", temp_path.name, seg.output_path
                                )

                            except Exception as move_err:
                                raise CutMindError(
                                    "❌ Impossible de déplacer le fichier.",
                                    code=ErrCode.NOFILE,
                                    ctx=get_step_ctx(
                                        {
                                            "final_output": seg.output_path,
                                            "temp_path": temp_path,
                                            "seg_id": seg.id,
                                        }
                                    ),
                                    original_exception=move_err,
                                ) from move_err

                            if not Path(seg.output_path).exists():
                                raise CutMindError(
                                    "❌ Fichier manquant après remplacement.",
                                    code=ErrCode.NOFILE,
                                    ctx=get_step_ctx(
                                        {
                                            "final_output": seg.output_path,
                                            "temp_path": temp_path,
                                            "seg_id": seg.id,
                                        }
                                    ),
                                )

                            processed_count += 1
                        return processed_count

            except CutMindError as err:
                raise err.with_context(
                    get_step_ctx({"video.name": self.video.name, "video.status": self.video.status})
                ) from err
            except Exception as exc:
                raise CutMindError(
                    "❌ Erreur inatendue durant l'envoi à Check Segments.",
                    code=ErrCode.UNEXPECTED,
                    ctx=get_step_ctx({"video.name": self.video.name, "video.status": self.video.status}),
                    original_exception=exc,
                ) from exc

        if processed_count == 0:
            self.logger.info("📭 Aucun segment traité lors de ce cycle.")
        else:
            self.logger.info("✅ %d segments envoyés et traités via Check Segments.", processed_count)

        self.logger.info("🏁 Cycle Check Segments terminé.")
        return processed_count
