"""
RouterWorker
============

Envoie automatiquement les segments 'validated' mais hors standard
(résolution < 1080p ou fps != 60) vers ComfyUI-Router.

- Sélectionne les vidéos concernées
- Copie les fichiers dans le répertoire d'import de Router
- Met à jour les statuts dans la base (segments + vidéos)
"""

from dataclasses import dataclass
from pathlib import Path

from check.executors.segments import check_video_compliance, inspect_video
from check.histo.business_rules import BusinessAction, evaluate_segment_business_rules
from check.histo.processing_checks import evaluate_video_compliance
from check.histo.processing_log import processing_step
from db.repository import CutMindRepository
from shared.executors.ffmpeg_convert import convert_safe_video_format
from shared.models.db_models import Segment, Video
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.models.timer_manager import Timer
from shared.services.file_mover import FileMover
from shared.services.gpu_guard import guard_gpu_or_requeue
from shared.services.video_preparation import prepare_video
from shared.status_orchestrator.statuses import OrchestratorStatus, SegmentStatus
from shared.utils.config import (
    COLOR_BLUE,
    COLOR_CYAN,
    COLOR_GREEN,
    COLOR_PURPLE,
    COLOR_RED,
    COLOR_RESET,
    COLOR_YELLOW,
    INPUT_DIR,
    OUTPUT_DIR,
    TRASH_DIR_SC,
)
from shared.utils.logger import get_logger
from shared.utils.trash import delete_files, move_to_trash


@dataclass(slots=True)
class CheckSummary:
    total: int = 0
    compliant: int = 0
    normalized: int = 0
    metadata_fixed: int = 0
    sent_to_ia: int = 0
    trashed: int = 0
    warnings: int = 0


class CheckSegments:
    """
    Gère l'envoi automatique des segments non conformes vers le flow adéquat.
    """

    def __init__(self, vid: Video, segments: list[Segment]):
        self.logger = get_logger("CutMind-Check_Segments")
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

        summary = CheckSummary(total=len(self.segments))
        processed_count = 0

        self.logger.info("🎞️ Vidéo '%s' nb segments: %i", self.video.name, len(self.segments))
        if guard_gpu_or_requeue(logger=self.logger):
            # 3️⃣ Transaction : copie + maj DB
            with Timer(f"Traitement Check Segments pour la vidéo : {self.video.name}", self.logger):
                try:
                    delete_files(path=Path(INPUT_DIR), ext="*.mp4")

                    for seg in self.segments:
                        with processing_step(self.video, seg, action="Check Segments") as history:
                            if not seg.output_path or not seg.id:
                                raise Exception("Impossible de récupérer le segment.")

                            with Timer(f"Traitement du segment : {seg.filename_predicted}", self.logger):
                                metadata_prep = prepare_video(Path(seg.output_path), logger=self.logger)
                                biz_status, biz_message, biz_action = evaluate_segment_business_rules(
                                    segment=seg,
                                    metadata=metadata_prep,
                                )

                                if biz_action == BusinessAction.TRASH:
                                    summary.trashed += 1
                                    self.logger.warning("🗑️ Segment %s déplacé en corbeille", seg.id)

                                    move_to_trash(file_path=Path(seg.output_path), trash_root=TRASH_DIR_SC)
                                    self.repo.delete_segment(int(seg.id))
                                    history.status = "trashed"
                                    history.message = biz_message
                                    continue

                                if biz_action == BusinessAction.SEND_TO_IA:
                                    summary.sent_to_ia += 1
                                    self.logger.info("🔁 Segment %s renvoyé vers IA", seg.id)

                                    seg.pipeline_target = OrchestratorStatus.SEGMENT_TO_IA
                                    self.repo.update_segment_validation(seg)

                                    history.status = "to_ia"
                                    history.message = biz_message
                                    continue

                                if biz_action == BusinessAction.FIX_METADATA:
                                    self.logger.info("🔧 Correction metadata segment %s", seg.id)

                                    self.repo.update_segment_from_metadata(seg.id, metadata_prep)
                                    summary.metadata_fixed += 1
                                    history.status = "fixed_metadata"
                                    history.message = biz_message

                                if biz_action == BusinessAction.WARNING_ONLY:
                                    summary.warnings += 1
                                    history.status = "warning"
                                    history.message = biz_message

                                metadata = inspect_video(Path(seg.output_path))

                                is_compliant, mismatches = check_video_compliance(metadata)

                                if is_compliant:
                                    summary.compliant += 1
                                    self.logger.info(
                                        "Video %s est conforme.",
                                        seg.filename_predicted,
                                    )
                                    seg.status = SegmentStatus.VALIDATED_CHECK
                                    seg.pipeline_target = SegmentStatus.TO_MOVE
                                    self.repo.update_segment_validation(seg)
                                    continue

                                self.logger.info(
                                    "Video %s non conforme : %s",
                                    seg.filename_predicted,
                                    mismatches,
                                )

                                self.logger.info(f"Video {seg.filename_predicted} n'est pas conforme.")
                                dst: Path = Path(INPUT_DIR) / f"{seg.filename_predicted}.mp4"
                                self.file_mover.safe_copy(Path(seg.output_path), dst)
                                self.logger.info(f"Video {seg.filename_predicted} copiée vers {dst}")

                                out_path: Path = OUTPUT_DIR / f"{dst.stem}.normalized.mp4"
                                convert_safe_video_format(str(dst), str(out_path), logger=self.logger)
                                self.logger.info(f"Video {seg.filename_predicted} normalisée.")
                                dst.unlink()

                                try:
                                    self.logger.debug(
                                        "appel safe_replace : final_output=%s, target_path=%s",
                                        out_path,
                                        seg.output_path,
                                    )
                                    FileMover.safe_replace(out_path, Path(seg.output_path), self.logger)
                                    self.logger.info(
                                        "📦 Fichier remplacé (via safe_copy) : %s → %s", out_path.name, seg.output_path
                                    )

                                except Exception as move_err:
                                    raise CutMindError(
                                        "❌ Impossible de déplacer le fichier.",
                                        code=ErrCode.NOFILE,
                                        ctx=get_step_ctx(
                                            {
                                                "final_output": seg.output_path,
                                                "out_path": out_path,
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
                                                "out_path": out_path,
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
                                seg.pipeline_target = SegmentStatus.TO_MOVE
                                self.repo.update_segment_validation(seg)
                                summary.normalized += 1
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
        self.log_summary(summary)
        self.logger.info("🏁 Cycle Check Segments terminé.")
        return processed_count

    def log_summary(
        self,
        summary: CheckSummary,
    ) -> None:
        """Log le résumé coloré du contrôle des segments."""

        def color_count(value: int) -> str:
            return COLOR_GREEN if value > 0 else COLOR_RED

        self.logger.info(
            "%s🧾 Résumé Check Segments : %s%s%s",
            COLOR_PURPLE,
            COLOR_CYAN,
            self.video.name,
            COLOR_RESET,
        )

        self.logger.info(
            "%s📌 Segments       : %s%d%s",
            COLOR_BLUE,
            COLOR_CYAN,
            summary.total,
            COLOR_RESET,
        )

        self.logger.info(
            "%s📌 Conformes      : %s%d%s",
            COLOR_BLUE,
            color_count(summary.compliant),
            summary.compliant,
            COLOR_RESET,
        )

        self.logger.info(
            "%s📌 Métadonnées    : %s%d corrigée(s)%s",
            COLOR_BLUE,
            COLOR_GREEN,
            summary.metadata_fixed,
            COLOR_RESET,
        )

        self.logger.info(
            "%s📌 Normalisés     : %s%d%s",
            COLOR_BLUE,
            color_count(summary.normalized),
            summary.normalized,
            COLOR_RESET,
        )

        self.logger.info(
            "%s📌 Renvoyés IA    : %s%d%s",
            COLOR_BLUE,
            color_count(summary.sent_to_ia),
            summary.sent_to_ia,
            COLOR_RESET,
        )

        self.logger.info(
            "%s📌 Corbeille      : %s%d%s",
            COLOR_BLUE,
            COLOR_RED if summary.trashed > 0 else COLOR_GREEN,
            summary.trashed,
            COLOR_RESET,
        )

        self.logger.info(
            "%s📌 Avertissements : %s%d%s",
            COLOR_BLUE,
            COLOR_YELLOW if summary.warnings > 0 else COLOR_GREEN,
            summary.warnings,
            COLOR_RESET,
        )


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
