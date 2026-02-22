from __future__ import annotations

from pathlib import Path
import re
import uuid

from b_db.repository import CutMindRepository
from f_validation.services.ffmpeg_concat_segments import ffmpeg_concat_segments
from shared.models.db_models import Segment
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.status_orchestrator.statuses import OrchestratorStatus
from shared.utils.config import TRASH_DIR_SC
from shared.utils.logger import LoggerProtocol, ensure_logger
from shared.utils.trash import move_to_trash


def perform_merge(
    segment: Segment,
    merge_ids: list[int],
    logger: LoggerProtocol | None = None,
) -> None:
    """
    Merge un segment courant avec d'autres segments listés via CSV.
    Le segment courant est implicitement inclus en premier.

    Résultat :
    - création d'un nouveau segment
    - suppression des anciens segments
    - nouveau segment repasse en validation manuelle (pending_check)
    """
    logger = ensure_logger(logger, __name__)
    repo = CutMindRepository()

    try:
        # --- 1️⃣ Validations de base ---
        if not segment or not segment.id:
            raise CutMindError(
                "❌ Segment invalide pour merge.",
                code=ErrCode.UNEXPECTED,
                ctx=get_step_ctx(),
            )

        if not merge_ids:
            return

        if segment.id in merge_ids:
            raise CutMindError(
                "❌ Merge invalide : le segment courant est déjà inclus implicitement.",
                code=ErrCode.BADFORMAT,
                ctx=get_step_ctx({"segment_id": segment.id, "merge_ids": merge_ids}),
            )

        # --- 2️⃣ Chargement des segments à merger ---
        other_segments = repo.get_segments_by_ids(merge_ids)

        if len(other_segments) != len(merge_ids):
            raise CutMindError(
                "❌ Merge invalide : certains segments sont introuvables.",
                code=ErrCode.DB,
                ctx=get_step_ctx({"merge_ids": merge_ids}),
            )

        # Vérifications strictes
        for seg in other_segments:
            if seg.video_id != segment.video_id:
                raise CutMindError(
                    "❌ Merge interdit : segments de vidéos différentes.",
                    code=ErrCode.BADFORMAT,
                    ctx=get_step_ctx({"segment_id": segment.id, "other_segment_id": seg.id}),
                )

        # --- 3️⃣ Ordre strict : segment courant puis IDs CSV ---
        ordered_segments = [segment]
        id_to_segment = {s.id: s for s in other_segments}
        ordered_segments.extend(id_to_segment[i] for i in merge_ids)

        input_paths: list[Path] = []
        for seg in ordered_segments:
            p = Path(str(seg.output_path))
            if not p.exists():
                raise CutMindError(
                    "❌ Fichier segment introuvable pour merge.",
                    code=ErrCode.UNEXPECTED,
                    ctx=get_step_ctx({"segment_id": seg.id, "path": p}),
                )
            input_paths.append(p)

        # --- 4️⃣ Concaténation ffmpeg ---
        output_dir = input_paths[0].parent / "merge"
        output_dir.mkdir(parents=True, exist_ok=True)

        new_uid = str(uuid.uuid4())
        output_path = output_dir / f"seg_merge_{segment.id:04d}_{new_uid}.mp4"

        ffmpeg_concat_segments(
            input_files=[str(p) for p in input_paths],
            output_file=str(output_path),
            logger=logger,
        )

        # Vérification anti-fichier vide
        if not output_path.exists() or output_path.stat().st_size < 50 * 1024:
            raise CutMindError(
                "❌ Fichier merge invalide (taille trop faible).",
                code=ErrCode.UNEXPECTED,
                ctx=get_step_ctx({"output_path": output_path}),
            )

        # --- 5️⃣ Création du nouveau segment ---
        total_duration = sum(s.duration or 0 for s in ordered_segments)

        new_seg = Segment(
            uid=new_uid,
            video_id=segment.video_id,
            start=ordered_segments[0].start,
            end=ordered_segments[-1].end,
            duration=total_duration,
            status=OrchestratorStatus.SEGMENT_CUT_DONE,
            pipeline_target=OrchestratorStatus.SEGMENT_IN_CUT_VALIDATION,
            confidence=0.00,
            description="",
            fps=segment.fps,
            resolution=segment.resolution,
            codec=segment.codec,
            bitrate=segment.bitrate,
            filename_predicted=output_path.name,
            output_path=str(output_path),
            source_flow="manual_csv",
            merged_from=[s.uid for s in ordered_segments],
        )

        repo._insert_segment(new_seg)

        # --- 6️⃣ Nettoyage : suppression des anciens segments ---
        for seg in ordered_segments:
            try:
                move_to_trash(Path(str(seg.output_path)), TRASH_DIR_SC)
                if not seg.id:
                    continue
                repo.delete_segment(seg.id)
            except Exception as exc:
                logger.warning(
                    "⚠️ Impossible de supprimer le segment %s : %s",
                    seg.id,
                    exc,
                )

        logger.info(
            "🔗 Merge OK → nouveau segment %s (%d segments fusionnés)",
            new_seg.uid,
            len(ordered_segments),
        )

    except CutMindError as err:
        raise err.with_context(get_step_ctx()) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur lors du traitement merge via CSV.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx(),
        ) from exc


def parse_merge_ids(status: str) -> list[int]:
    """
    Extrait les IDs de segments à merger à partir du champ 'status'.

    Exemples :
        "merge:12,15"     → [12, 15]
        "merge : 3, 9"    → [3, 9]
        "MERGE:7"         → [7]
    """
    if not status:
        return []

    s = re.sub(r"\s+", "", status.strip().lower())

    if not s.startswith("merge:"):
        return []

    try:
        return [int(x) for x in re.findall(r"\d+", s)]
    except ValueError:
        return []
