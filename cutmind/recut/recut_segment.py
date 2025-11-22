""" """

from __future__ import annotations

from pathlib import Path
import re
import uuid

from cutmind.db.repository import CutMindRepository
from cutmind.models_cm.db_models import Segment
from cutmind.recut.ffmpeg_recut import ffmpeg_cut_one_segment
from shared.utils.config import TRASH_DIR_SC
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from shared.utils.trash import move_to_trash


@with_child_logger
def perform_recut(
    segment: Segment,
    recut_points: list[float],
    logger: LoggerProtocol | None = None,
) -> None:
    logger = ensure_logger(logger, __name__)
    repo = CutMindRepository()
    if not segment or not segment.start or not segment.end or not segment.id:
        return
    input_path = Path(str(segment.output_path))

    if not input_path.exists():
        logger.error("❌ Fichier segment introuvable : %s", input_path)
        return

    recut_points = sorted(x for x in recut_points if segment.start < segment.start + x < segment.end)

    # Construit les fenêtres temporelles
    cuts = [segment.start, *(segment.start + p for p in recut_points), segment.end]

    output_dir = input_path.parent / "recut"
    output_dir.mkdir(parents=True, exist_ok=True)

    for i in range(len(cuts) - 1):
        start = cuts[i]
        end = cuts[i + 1]

        # UID UNIQUE PAR SEGMENT
        new_uid = str(uuid.uuid4())

        output_path = output_dir / f"seg_{segment.id:04d}_{new_uid}.mp4"

        try:
            ffmpeg_cut_one_segment(input_path, start, end, output_path, logger=logger)
        except Exception as e:
            logger.error("❌ Erreur ffmpeg (cut %s): %s", segment.uid, e)
            continue

        new_seg = Segment(
            uid=new_uid,
            video_id=segment.video_id,
            start=start,
            end=end,
            duration=end - start,
            status="pending_check",
            confidence=0.00,
            description="",
            fps=segment.fps,
            resolution=segment.resolution,
            codec=segment.codec,
            bitrate=segment.bitrate,
            filename_predicted=output_path.name,
            output_path=str(output_path),
            source_flow="manual_csv",
            merged_from=[segment.uid],
        )

        repo._insert_segment(new_seg, logger=logger)

    # une fois TOUT recut → poubelle l’ancien
    move_to_trash(input_path, TRASH_DIR_SC, logger=logger)
    repo.delete_segment(segment.id, logger=logger)

    logger.info("🔪 Recut OK pour %s → %d nouveaux segments", segment.uid, len(cuts) - 1)


def parse_recut_points(status: str) -> list[float]:
    """
    Extrait les points de découpe à partir du champ 'status'.
    Exemples :
        "recut:45,120" → [45.0, 120.0]
        "recut : 110"  → [110.0]
        "Recut: 85.5"  → [85.5]
        "85"            → [85.0]
    """
    if not status:
        return []

    # Normalisation
    s = re.sub(r"\s+", "", status.strip().lower())  # retire tous les espaces, ex: "recut : 110" → "recut:110"

    # recut:xx,yy,zz
    if s.startswith("recut:"):
        try:
            return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", s)]
        except ValueError:
            return []

    # Si c’est juste un nombre
    if re.fullmatch(r"\d+(?:\.\d+)?", s):
        return [float(s)]

    return []
