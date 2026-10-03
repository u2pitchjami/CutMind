from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import uuid

from db.repository import CutMindRepository
from shared.models.db_models import Segment
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.services.file_mover import FileMover
from shared.status_orchestrator.statuses import OrchestratorStatus
from shared.utils.config import TRASH_DIR_SC
from shared.utils.logger import LoggerProtocol, ensure_logger
from shared.utils.trash import move_to_trash
from validation.services.ffmpeg_concat_segments import ffmpeg_concat_segments


@dataclass(slots=True, frozen=True)
class MergeRequest:
    """Paramètres d'une commande de merge issue du CSV."""

    merge_ids: list[int]
    keep_sources: bool = False


def parse_merge_request(status: str) -> MergeRequest | None:
    """
    Extrait une commande de merge depuis le champ 'status'.

    Exemples :
        "merge:12,15"
            -> MergeRequest([12, 15], keep_sources=False)

        "merge : 3, 9"
            -> MergeRequest([3, 9], keep_sources=False)

        "MERGE:7"
            -> MergeRequest([7], keep_sources=False)

        "merge_keep:12,15"
            -> MergeRequest([12, 15], keep_sources=True)

        "merge_keep : 3, 9"
            -> MergeRequest([3, 9], keep_sources=True)
    """
    if not status:
        return None

    normalized_status = re.sub(
        r"\s+",
        "",
        status.strip().lower(),
    )

    if normalized_status.startswith("merge_keep:"):
        keep_sources = True
    elif normalized_status.startswith("merge:"):
        keep_sources = False
    else:
        return None

    try:
        merge_ids = [int(value) for value in re.findall(r"\d+", normalized_status)]
    except ValueError:
        return None

    if not merge_ids:
        return None

    return MergeRequest(
        merge_ids=merge_ids,
        keep_sources=keep_sources,
    )


def perform_merge(
    segment: Segment,
    merge_ids: list[int],
    keep_sources: bool = False,
    logger: LoggerProtocol | None = None,
) -> None:
    """
    Merge un segment courant avec d'autres segments listés via CSV. Le segment courant est implicitement inclus en
    premier.

    Résultat :
    - création d'un nouveau segment
    - suppression des anciens segments
    - nouveau segment repasse en validation manuelle (pending_check)
    """
    logger = ensure_logger(logger, __name__)
    repo = CutMindRepository()
    file_mover = FileMover()

    try:
        # --- 1️⃣ Validations de base ---
        if not segment or not segment.id or segment.has_audio is None:
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
            has_audio=segment.has_audio,
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
            has_audio=segment.has_audio,
            audio_codec=segment.audio_codec,
            sample_rate=segment.sample_rate,
            channels=segment.channels,
            filename_predicted=output_path.name,
            output_path=str(output_path),
            source_flow="manual_csv",
            merged_from=[s.uid for s in ordered_segments],
        )

        new_id = repo._insert_segment(new_seg)

        new_seg_load = repo.get_segment_by_id(new_id)
        if not new_seg_load or not new_seg_load.output_path:
            raise CutMindError(
                "❌ Impossible de charger le nouveau segment après insertion.",
                code=ErrCode.DB,
                ctx=get_step_ctx({"new_segment_id": new_id}),
            )

        src_path = new_seg_load.output_path
        if not src_path:
            raise CutMindError(
                "❌ Nouveau segment sans chemin de sortie valide.",
                code=ErrCode.UNEXPECTED,
                ctx=get_step_ctx({"new_segment_id": new_id}),
            )
        src_path_parent2 = Path(src_path).parent.parent
        vidname = Path(src_path).parent.name
        if not src_path_parent2.exists():
            src_path_parent2.mkdir(parents=True, exist_ok=True)
        new_seg_load.predict_filename(base_dir=str(src_path_parent2), folder_name=str(vidname))
        repo.update_segment_validation(new_seg_load)
        file_mover.safe_replace(src=Path(src_path), dst=Path(new_seg_load.output_path), logger=logger)

        # --- 6️⃣ Nettoyage des segments sources ---
        if not keep_sources:
            for seg in ordered_segments:
                if seg.id is None:
                    logger.warning(
                        "⚠️ Impossible de supprimer un segment sans ID : %s",
                        seg.uid,
                    )
                    continue

                if not seg.output_path:
                    logger.warning(
                        "⚠️ Segment %s sans output_path, suppression ignorée.",
                        seg.id,
                    )
                    continue

                try:
                    move_to_trash(
                        Path(seg.output_path),
                        TRASH_DIR_SC,
                    )
                    repo.delete_segment(seg.id)

                except Exception as exc:  # pylint: disable=broad-exception-caught
                    logger.warning(
                        "⚠️ Impossible de supprimer le segment %s : %s",
                        seg.id,
                        exc,
                    )

        logger.info(
            "🔗 Merge OK → nouveau segment %s (%d segments fusionnés, sources %s)",
            new_seg.uid,
            len(ordered_segments),
            "conservées" if keep_sources else "supprimées",
        )

    except CutMindError as err:
        raise err.with_context(get_step_ctx()) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur lors du traitement merge via CSV.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx(),
        ) from exc
