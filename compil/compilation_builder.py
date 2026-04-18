import json
from pathlib import Path
import subprocess
from typing import Literal

from shared.models.db_models import Segment
from shared.utils.config import EXPORTS_COMPIL, TEMP_COMPIL
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger


@with_child_logger
def make_compilation(
    segments: list[Segment],
    output_path: Path = EXPORTS_COMPIL,
    temp_path: Path = TEMP_COMPIL,
    manifest_path: Path | None = EXPORTS_COMPIL,
    compress: Literal["copy", "cpu", "cuda"] = "cuda",
    logger: LoggerProtocol | None = None,
) -> None:
    logger = ensure_logger(logger, __name__)
    if not segments:
        logger.warning("❌ Aucun segment à compiler.")
        return

    concat_file = output_path.with_suffix(".txt")
    with open(concat_file, "w", encoding="utf-8") as f:
        for seg in segments:
            f.write(f"file '{Path(str(seg.output_path)).as_posix()}'\n")

    # --- Choix de l'encodage
    if compress == "copy":
        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(output_path)]

    elif compress == "cuda":
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c:v",
            "h264_nvenc",
            "-preset",
            "p4",
            "-cq",
            "19",
            "-pix_fmt",
            "yuv420p",
            "-profile:v",
            "high",
            "-movflags",
            "+faststart",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(output_path),
        ]

    else:  # fallback CPU
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-profile:v",
            "high",
            "-movflags",
            "+faststart",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(output_path),
        ]

    try:
        subprocess.run(cmd, check=True)
        logger.info("✅ Compilation générée : %s", output_path)

    except subprocess.CalledProcessError as e:
        logger.error("❌ Erreur lors de la compilation : %s", e)
        return

    # --- Manifest JSON
    if manifest_path:
        log_data = [
            {
                "uid": s.uid,
                "category": s.category,
                "duration": s.duration,
                "keywords": s.keywords,
                "filename": s.output_path,
            }
            for s in segments
        ]

        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=2)
        logger.info("📄 Manifest sauvegardé : %s", manifest_path)
