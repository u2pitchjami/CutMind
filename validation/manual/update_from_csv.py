"""
Import des modifications manuelles de segments depuis CSV.

Gère notamment :
- édition des métadonnées d'un segment ;
- validation manuelle ;
- retour vers l'IA ;
- suppression ;
- recut ;
- merge ;
- déplacement vers une autre vidéo ;
- renommage d'une vidéo.
"""

from __future__ import annotations

from contextlib import nullcontext
import csv
from dataclasses import dataclass
from pathlib import Path

from check.histo.processing_log import processing_step
from db.db_connection import db_conn, get_dict_cursor
from db.repository import CutMindRepository
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.status_orchestrator.statuses import OrchestratorStatus
from shared.utils.config import (
    CSV_ARCHIVE_PATH,
    CSV_LOG_PATH,
    MANUAL_CSV_PATH,
    OUTPUT_DIR_SC,
    POST_CUT_DIR_SC,
)
from shared.utils.logger import LoggerProtocol, ensure_logger
from shared.utils.remove_empty_dirs import remove_empty_dirs
from shared.utils.trash import purge_old_trash
from validation.manual.manual_utils import (
    archive_csv,
    build_new_data_from_csv_row,
    compare_segment,
    has_keywords,
    has_text,
    summarize_import,
    write_csv_log,
)
from validation.services.delete_segment import perform_segment_delete
from validation.services.merge_perform import parse_merge_request, perform_merge
from validation.services.recut_segment import parse_recut_points, perform_recut
from validation.services.rename_video import perform_video_rename


@dataclass(slots=True)
class ImportStats:
    """Statistiques d'un import CSV manuel."""

    checked: int = 0
    updated: int = 0
    deleted: int = 0
    unchanged: int = 0
    errors: int = 0

    def as_dict(self) -> dict[str, int]:
        """Retourne le format historique attendu par summarize_import()."""
        return {
            "checked": self.checked,
            "updated": self.updated,
            "deleted": self.deleted,
            "unchanged": self.unchanged,
            "errors": self.errors,
        }


def _get_segment_id(row: dict[str, str]) -> int | None:
    """Extrait et valide l'identifiant du segment depuis une ligne CSV."""
    raw_segment_id = row.get("segment_id")

    if not raw_segment_id:
        return None

    try:
        return int(raw_segment_id)
    except ValueError:
        return None


def _process_csv_row(
    row: dict[str, str],
    repo: CutMindRepository,
    stats: ImportStats,
    log_rows: list[dict[str, str]],
    logger: LoggerProtocol,
) -> None:
    """Traite une ligne du fichier CSV manuel."""
    segment_id = _get_segment_id(row)

    if segment_id is None:
        logger.warning(
            "⚠️ segment_id absent ou invalide : %r",
            row.get("segment_id"),
        )
        return

    stats.checked += 1

    try:
        video_id = repo.get_video_id_from_segment_id(segment_id)
        if not video_id:
            logger.warning(
                "⚠️ Aucune vidéo trouvée pour le segment %s.",
                segment_id,
            )
            return

        video = repo.get_video_with_segments(video_id=video_id)
        if video is None:
            logger.warning(
                "⚠️ Vidéo %s introuvable pour le segment %s.",
                video_id,
                segment_id,
            )
            return

        segment = next(
            (item for item in video.segments if item.id == segment_id),
            None,
        )
        if segment is None:
            logger.warning(
                "⚠️ Segment %s absent de la vidéo %s.",
                segment_id,
                video_id,
            )
            return

        new_data = build_new_data_from_csv_row(row)

        logger.debug(
            "🔍 Segment %s | Données CSV : %s",
            segment_id,
            new_data,
        )

        action = new_data["action"].lower().strip() if new_data["action"] else ""

        has_category = has_text(new_data["category"])
        has_description = has_text(new_data["description"])
        has_keywords_value = has_keywords(new_data["keywords"])
        has_confidence = new_data["confidence"] > 0.0

        logger.debug(
            "🔍 Segment %s | Nouveau statut CSV : %s",
            segment_id,
            action,
        )

        # --------------------------------------------------------------
        # Actions terminales
        # --------------------------------------------------------------

        if action in ("rename", "to_rename"):
            new_video_name = new_data["video_name"].strip()

            if new_video_name != video.name:
                moved_count = perform_video_rename(
                    video_id=video_id,
                    new_name=new_video_name,
                    repo=repo,
                    logger=logger,
                )

                stats.updated += 1
                log_rows.append(
                    {
                        "segment_id": str(segment_id),
                        "action": "renamed video",
                        "differences": (f"video_name; {moved_count} segments scheduled"),
                    }
                )

            return

        if action in ("delete", "to_delete"):
            perform_segment_delete(
                segment_id=segment_id,
                output_path=segment.output_path,
                repo=repo,
                logger=logger,
            )

            stats.deleted += 1
            log_rows.append(
                {
                    "segment_id": str(segment_id),
                    "action": "deleted",
                    "differences": "ALL",
                }
            )
            return

        recut_points = parse_recut_points(action)
        if recut_points:
            perform_recut(
                segment,
                recut_points,
                logger=logger,
            )

            stats.updated += 1
            log_rows.append(
                {
                    "segment_id": str(segment_id),
                    "action": f"recut @{recut_points}",
                    "differences": "recut",
                }
            )
            return

        merge_request = parse_merge_request(action)
        if merge_request is not None:
            perform_merge(
                segment=segment,
                merge_ids=merge_request.merge_ids,
                keep_sources=merge_request.keep_sources,
                logger=logger,
            )

            stats.updated += 1

            action = "merge keep" if merge_request.keep_sources else "merge"

            log_rows.append(
                {
                    "segment_id": str(segment_id),
                    "action": action,
                    "differences": (f"merge with {merge_request.merge_ids}"),
                }
            )
            return

        # --------------------------------------------------------------
        # Déplacement vers une autre vidéo
        #
        # Contrairement aux actions ci-dessus, move n'est pas terminal :
        # new_data["video_id"] doit atteindre update_segment_from_csv().
        # --------------------------------------------------------------

        if action in ("move", "to_move"):
            new_data["pipeline_target"] = OrchestratorStatus.SEGMENT_TO_MOVE
            logger.info(
                "✏️ segment %s à déplacer.",
                segment_id,
            )
            stats.updated += 1
            log_rows.append(
                {
                    "segment_id": str(segment_id),
                    "action": "moved to other video",
                    "differences": "video_id",
                }
            )
        else:
            # Hors commande move, les valeurs CSV ne peuvent pas modifier
            # l'appartenance du segment à sa vidéo.
            new_data["video_id"] = video.id
            new_data["video_name"] = video.name

        # --------------------------------------------------------------
        # Validation manuelle
        # --------------------------------------------------------------

        if action.lower() == "ok":
            new_data["status"] = OrchestratorStatus.SEGMENT_CUT_VALIDATED
            new_data["pipeline_target"] = OrchestratorStatus.SEGMENT_TO_ENHANCE
            new_data["description"] = ""
            new_data["keywords"] = []
            has_description = False
            has_keywords_value = False

            if has_category:
                new_data["confidence"] = 0.99

        if action == "val":
            missing = []
            if not has_category:
                missing.append("catégorie")
            if not has_description:
                missing.append("description")
            if not has_keywords_value:
                missing.append("mots-clés")
            if missing:
                raise ValueError("Validation finale refusée : données manquantes : " + ", ".join(missing))
            new_data["status"] = OrchestratorStatus.SEGMENT_VALIDATED
            new_data["pipeline_target"] = OrchestratorStatus.SEGMENT_TO_CHECK
            new_data["confidence"] = segment.confidence

        # --------------------------------------------------------------
        # Décision de pipeline IA
        # --------------------------------------------------------------

        logger.debug(
            ("🔍 Segment %s | category=%s | status=%s | description=%s | keywords=%s | confidence=%s"),
            segment_id,
            has_category,
            new_data["status"],
            has_description,
            has_keywords_value,
            has_confidence,
        )

        if (
            has_category
            and new_data["status"] == OrchestratorStatus.SEGMENT_CONFIDENCE_DONE
            and not (has_description or has_keywords_value or has_confidence)
        ):
            new_data["pipeline_target"] = OrchestratorStatus.SEGMENT_TO_IA

            stats.updated += 1
            log_rows.append(
                {
                    "segment_id": str(segment_id),
                    "action": "rework ia",
                    "differences": "category",
                }
            )

        # if has_category and has_description and has_keywords_value and has_confidence:
        #     new_data["pipeline_target"] = None

        # --------------------------------------------------------------
        # Mise à jour standard
        # --------------------------------------------------------------

        diffs = compare_segment(segment, new_data)

        if not diffs:
            stats.unchanged += 1
            log_rows.append(
                {
                    "segment_id": str(segment_id),
                    "action": "unchanged",
                    "differences": "",
                }
            )
            return

        with (
            processing_step(video, segment, action="Validation finale manuelle via CSV")
            if action == "val"
            else nullcontext()
        ) as history:
            repo.update_segment_from_csv(segment, new_data, diffs)
            repo.update_video(video)
            if history is not None:
                history.status = "ok"
                history.message = "Validation finale approuvée manuellement via CSV ; confidence conservée."

        stats.updated += 1
        log_rows.append(
            {
                "segment_id": str(segment_id),
                "action": (
                    "Validation finale manuelle via CSV"
                    if action == "val"
                    else "Cut Validation OK"
                    if action == "ok"
                    else "updated"
                ),
                "differences": ", ".join(diffs),
            }
        )

    except Exception as exc:  # pylint: disable=broad-exception-caught
        stats.errors += 1

        logger.exception(
            "❌ Erreur segment %s : %s",
            segment_id,
            exc,
        )

        log_rows.append(
            {
                "segment_id": str(segment_id),
                "action": "error",
                "differences": str(exc),
            }
        )


def update_segments_csv(
    status_csv: str = "manual_review",
    manual_csv: Path = Path(MANUAL_CSV_PATH),
    csv_log: Path = Path(CSV_LOG_PATH),
    logger: LoggerProtocol | None = None,
) -> None:
    """Importe les modifications manuelles du CSV dans CutMind."""
    logger = ensure_logger(logger, __name__)

    stats = ImportStats()
    log_rows: list[dict[str, str]] = []

    try:
        if not manual_csv.exists():
            logger.warning(
                "❌ Fichier CSV manuel absent : %s",
                manual_csv,
            )
            return

        repo = CutMindRepository()

        with db_conn(logger=logger) as conn:
            with (
                get_dict_cursor(conn),
                open(
                    manual_csv,
                    newline="",
                    encoding="utf-8",
                ) as csv_file,
            ):
                reader = csv.DictReader(csv_file)

                for row in reader:
                    _process_csv_row(
                        row=row,
                        repo=repo,
                        stats=stats,
                        log_rows=log_rows,
                        logger=logger,
                    )

                conn.commit()

            archived_path = archive_csv(
                manual_csv,
                CSV_ARCHIVE_PATH,
                logger,
            )
            logger.info(
                "🗄️ Fichier CSV archivé vers %s",
                archived_path,
            )

            purge_old_trash(
                CSV_ARCHIVE_PATH,
                days=60,
                logger=logger,
            )

            remove_empty_dirs(
                root_path=OUTPUT_DIR_SC,
                logger=logger,
            )
            remove_empty_dirs(
                root_path=POST_CUT_DIR_SC,
                logger=logger,
            )

        write_csv_log(
            csv_log,
            log_rows,
        )
        summarize_import(
            stats.as_dict(),
            csv_log,
            logger=logger,
        )

        # À réactiver lorsque nécessaire :
        # validation(status=status_csv, logger=logger)

        _ = status_csv

    except CutMindError as err:
        raise err.with_context(get_step_ctx({"manual_csv": manual_csv})) from err

    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors du traitement du fichier csv manuel.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"manual_csv": manual_csv}),
        ) from exc
