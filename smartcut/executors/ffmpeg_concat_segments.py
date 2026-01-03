from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.logger import LoggerProtocol


def ffmpeg_concat_segments(
    *,
    input_files: list[str],
    output_file: str,
    logger: LoggerProtocol,
) -> None:
    """
    Concatène plusieurs fichiers vidéo dans l'ordre donné via ffmpeg (concat demuxer).

    - Aucun ré-encodage
    - Ordre strict respecté
    - Lève une exception en cas d'échec
    """
    if not input_files or len(input_files) < 2:
        raise CutMindError(
            "Concat ffmpeg invalide : au moins deux fichiers requis.",
            code=ErrCode.BADFORMAT,
            ctx=get_step_ctx({"input_files": input_files}),
        )

    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # --- 1️⃣ Création du fichier liste temporaire ---
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".txt",
            delete=False,
        ) as f:
            list_file = Path(f.name)
            for file_path in input_files:
                p = Path(file_path)
                if not p.exists():
                    raise CutMindError(
                        "Fichier d'entrée introuvable pour concat.",
                        code=ErrCode.UNEXPECTED,
                        ctx=get_step_ctx({"path": p}),
                    )
                # concat demuxer exige file 'path'
                f.write(f"file '{p.as_posix()}'\n")
    except Exception as exc:
        raise CutMindError(
            "Erreur lors de la création du fichier concat.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx(),
        ) from exc

    # --- 2️⃣ Commande ffmpeg ---
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c",
        "copy",
        str(output_path),
    ]

    logger.debug("🎞️ ffmpeg concat command: %s", " ".join(cmd))

    # --- 3️⃣ Exécution ---
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            logger.error("❌ ffmpeg concat failed: %s", result.stderr)
            raise CutMindError(
                "Erreur ffmpeg lors de la concaténation.",
                code=ErrCode.UNEXPECTED,
                ctx=get_step_ctx(
                    {
                        "returncode": result.returncode,
                        "stderr": result.stderr,
                    }
                ),
            )

        logger.info(
            "🎬 ffmpeg concat OK → %s (%d fichiers)",
            output_path.name,
            len(input_files),
        )

    finally:
        # --- 4️⃣ Nettoyage fichier temporaire ---
        try:
            list_file.unlink(missing_ok=True)
        except OSError:
            logger.warning("Impossible de supprimer le fichier temporaire %s", list_file)
