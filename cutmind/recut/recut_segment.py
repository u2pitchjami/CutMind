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
    """Recoupe un segment déjà extrait — sécurisé avec validations strictes."""
    logger = ensure_logger(logger, __name__)
    repo = CutMindRepository()

    if not segment or not segment.id or not segment.duration:
        logger.error("Segment invalide pour recut : %s", segment)
        return

    input_path = Path(str(segment.output_path))
    if not input_path.exists():
        logger.error("❌ Fichier segment introuvable : %s", input_path)
        return

    # 1 — Vérification stricte
    if any(p <= 0 or p >= segment.duration for p in recut_points):
        logger.error("❌ Recut refusé : points invalides %s (durée segment = %.2fs)", recut_points, segment.duration)
        return

    valid_points = sorted(recut_points)
    cuts = [0.0, *valid_points, float(segment.duration)]

    output_dir = input_path.parent / "recut"
    output_dir.mkdir(parents=True, exist_ok=True)

    generated_files: list[Path] = []
    new_segments = []

    # 2 — Génération segments
    for i in range(len(cuts) - 1):
        start = cuts[i]
        end = cuts[i + 1]

        new_uid = str(uuid.uuid4())
        output_path = output_dir / f"seg_{segment.id:04d}_{new_uid}.mp4"

        try:
            ffmpeg_cut_one_segment(
                input_path=input_path,
                start=start,
                end=end,
                output_path=output_path,
                logger=logger,
            )
        except Exception as exc:
            logger.error("❌ Erreur ffmpeg (cut): %s", exc)
            continue

        # 3 — Vérification du fichier généré (anti-1Ko)
        if not output_path.exists() or output_path.stat().st_size < 50 * 1024:
            logger.error("❌ Fichier recut invalide : %s (taille trop faible)", output_path)
            if output_path.exists():
                output_path.unlink()
            continue

        generated_files.append(output_path)

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

        new_segments.append(new_seg)

    # 4 — SÉCURITÉ : si tout n’est pas généré correctement → on NE SUPPRIME RIEN
    if len(new_segments) != len(cuts) - 1:
        logger.error(
            "❌ Recut échoué : %d/%d segments valides seulement. Original conservé.",
            len(new_segments),
            len(cuts) - 1,
        )
        # Nettoyage propre
        for p in generated_files:
            try:
                p.unlink()
            except OSError:
                logger.warning("Impossible de supprimer %s", p)
        return

    # 5 — Recuts OK → on supprime l’ancien
    for seg in new_segments:
        repo._insert_segment(seg, logger=logger)

    move_to_trash(input_path, TRASH_DIR_SC)
    repo.delete_segment(segment.id, logger=logger)

    logger.info(
        "🔪 Recut OK pour %s → %d nouveaux segments",
        segment.uid,
        len(new_segments),
    )


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
