""" """

from __future__ import annotations

from pathlib import Path
import re
import uuid

from cutmind.db.repository import CutMindRepository
from cutmind.models_cm.db_models import Segment
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.config import TRASH_DIR_SC
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from shared.utils.settings import get_settings
from shared.utils.trash import move_to_trash
from smartcut.executors.ffmpeg_cut_executor import FfmpegCutExecutor

settings = get_settings()

USE_CUDA = settings.smartcut.use_cuda
PRESET = settings.smartcut.preset_gpu if USE_CUDA else settings.smartcut.preset_cpu
VCODEC = settings.smartcut.vcodec_gpu if USE_CUDA else settings.smartcut.vcodec_cpu
CRF = settings.smartcut.crf


@with_child_logger
def perform_recut(
    segment: Segment,
    recut_points: list[float],
    logger: LoggerProtocol | None = None,
) -> None:
    """Recoupe un segment déjà extrait — sécurisé avec validations strictes."""
    logger = ensure_logger(logger, __name__)
    repo = CutMindRepository()

    try:
        if not segment or not segment.id or not segment.duration:
            raise CutMindError(
                "❌ Segment invalide pour recut.",
                code=ErrCode.UNEXPECTED,
                ctx=get_step_ctx(),
            )

        input_path = Path(str(segment.output_path))
        if not input_path.exists():
            raise CutMindError(
                "❌ Fichier segment introuvable.",
                code=ErrCode.UNEXPECTED,
                ctx=get_step_ctx({"input_path": input_path}),
            )

        # 1 — Vérification stricte
        if any(p <= 0 or p >= segment.duration for p in recut_points):
            raise CutMindError(
                "❌ Recut refusé : points invalides.",
                code=ErrCode.UNEXPECTED,
                ctx=get_step_ctx(
                    {"segment_id": segment.id, "recut_points": recut_points, "segment_duration": segment.duration}
                ),
            )

        valid_points = sorted(recut_points)
        cuts = [0.0, *valid_points, float(segment.duration)]

        output_dir = input_path.parent / "recut"
        output_dir.mkdir(parents=True, exist_ok=True)

        generated_files: list[Path] = []
        new_segments = []
        executor = FfmpegCutExecutor()

        # 2 — Génération segments
        for i in range(len(cuts) - 1):
            start = cuts[i]
            end = cuts[i + 1]

            new_uid = str(uuid.uuid4())
            output_path = output_dir / f"seg_{segment.id:04d}_{new_uid}.mp4"

            try:
                executor.cut(str(input_path), start, end, str(output_path), USE_CUDA, VCODEC, CRF, PRESET)
                # ffmpeg_cut_one_segment(
                #     input_path=input_path,
                #     start=start,
                #     end=end,
                #     output_path=output_path,
                #     logger=logger,
                # )
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
            repo._insert_segment(seg)

        move_to_trash(input_path, TRASH_DIR_SC)
        repo.delete_segment(segment.id)

        logger.info(
            "🔪 Recut OK pour %s → %d nouveaux segments",
            segment.uid,
            len(new_segments),
        )
    except CutMindError as err:
        raise err.with_context(get_step_ctx()) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur lors du traitement recut via csv.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx(),
        ) from exc


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
