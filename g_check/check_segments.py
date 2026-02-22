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

from b_db.repository import CutMindRepository
from g_check.executors.segments import inspect_video, is_video_compliant
from g_check.histo.business_rules import BusinessAction, evaluate_segment_business_rules
from g_check.histo.processing_checks import evaluate_video_compliance
from g_check.histo.processing_log import processing_step
from shared.executors.ffmpeg_convert import convert_safe_video_format
from shared.models.db_models import Segment, Video
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.models.timer_manager import Timer
from shared.services.file_mover import FileMover
from shared.services.video_preparation import prepare_video
from shared.status_orchestrator.statuses import OrchestratorStatus, SegmentStatus
from shared.utils.config import TRASH_DIR_SC, WORKDIR_CM
from shared.utils.logger import LoggerProtocol, ensure_logger
from shared.utils.trash import delete_files, move_to_trash


class CheckSegments:
    """Gère l'envoi automatique des segments non conformes vers ComfyUI Router."""

    def __init__(self, vid: Video, segments: list[Segment], logger: LoggerProtocol | None = None):
        self.logger = ensure_logger(logger, __name__)
        self.video = vid
        self.segments = segments
        self.file_mover = FileMover()
        self.repo = CutMindRepository()

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
                delete_files(path=Path(WORKDIR_CM), ext="*.mp4")

                for seg in self.segments:
                    with processing_step(self.video, seg, action="Check Segments") as history:
                        if not seg.output_path or not seg.id:
                            raise Exception("Impossible de récupérer le segment.")

                        with Timer(f"Traitement du segment : {seg.filename_predicted}", self.logger):
                            metadata_prep = prepare_video(Path(seg.output_path))
                            biz_status, biz_message, biz_action = evaluate_segment_business_rules(
                                segment=seg,
                                metadata=metadata_prep,
                            )

                            if biz_action == BusinessAction.TRASH:
                                self.logger.warning("🗑️ Segment %s déplacé en corbeille", seg.id)

                                move_to_trash(file_path=Path(seg.output_path), trash_root=TRASH_DIR_SC)
                                self.repo.delete_segment(int(seg.id))
                                history.status = "trashed"
                                history.message = biz_message
                                continue

                            if biz_action == BusinessAction.SEND_TO_IA:
                                self.logger.info("🔁 Segment %s renvoyé vers IA", seg.id)

                                seg.pipeline_target = OrchestratorStatus.SEGMENT_TO_IA
                                self.repo.update_segment_validation(seg)

                                history.status = "to_ia"
                                history.message = biz_message
                                continue

                            if biz_action == BusinessAction.FIX_METADATA:
                                self.logger.info("🔧 Correction metadata segment %s", seg.id)

                                self.repo.update_segment_from_metadata(seg.id, metadata_prep)

                                history.status = "fixed_metadata"
                                history.message = biz_message

                            if biz_action == BusinessAction.WARNING_ONLY:
                                history.status = "warning"
                                history.message = biz_message

                            metadata = inspect_video(Path(seg.output_path))

                            if is_video_compliant(metadata):
                                self.logger.info(f"Video {seg.filename_predicted} est conforme.")
                                seg.status = SegmentStatus.VALIDATED_CHECK
                                self.repo.update_segment_validation(seg)
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

                            metadata = inspect_video(Path(seg.output_path))
                            tech_status, tech_message = evaluate_video_compliance(metadata)
                            final_status, final_message = merge_check_results(
                                tech_status,
                                tech_message,
                                biz_status,
                                biz_message,
                            )
                            history.status = final_status
                            history.message = final_message
                            seg.status = SegmentStatus.VALIDATED_CHECK
                            self.repo.update_segment_validation(seg)
                            processed_count += 1

            except CutMindError as err:
                raise err.with_context(
                    get_step_ctx({"video.name": self.video.name, "video.status": self.video.status})
                ) from err
            except Exception as exc:
                raise CutMindError(
                    "❌ Erreur inatendue durant l'envoi à Check Segments.",
                    code=ErrCode.UNEXPECTED,
                    ctx=get_step_ctx({"video.name": self.video.name, "video.status": self.video.status}),
                ) from exc

        if processed_count == 0:
            self.logger.info("📭 Aucun segment traité lors de ce cycle.")
        else:
            self.logger.info("✅ %d segments envoyés et traités via Check Segments.", processed_count)

        self.logger.info("🏁 Cycle Check Segments terminé.")
        return processed_count


def merge_check_results(
    tech_status: str,
    tech_message: str,
    biz_status: str,
    biz_message: str,
) -> tuple[str, str]:
    """
    Fusionne résultats technique + métier.
    Priorité : error > warning > ok
    """

    statuses = [tech_status, biz_status]

    if "error" in statuses:
        final_status = "error"
    elif "warning" in statuses:
        final_status = "warning"
    else:
        final_status = "ok"

    messages = []

    if tech_message:
        messages.append(f"[TECH] {tech_message}")

    if biz_message:
        messages.append(f"[BIZ] {biz_message}")

    final_message = " | ".join(messages)

    return final_status, final_message
