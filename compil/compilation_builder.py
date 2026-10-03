from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

from shared.ffmpegjob.ffjob import FFmpegInput, FFmpegJob, run_ffmpeg_job
from shared.models.db_models import Segment
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.logger import LoggerProtocol, ensure_logger


def _has_audio_stream(
    path: Path,
    logger: LoggerProtocol,
) -> bool:
    """Return True when the media file contains at least one audio stream."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=index",
        "-of",
        "csv=p=0",
        str(path),
    ]

    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        logger.error(
            "FFprobe failed for %s: %s",
            path,
            exc.stderr,
        )
        raise CutMindError(
            f"Impossible d'analyser les flux audio : {path}",
            code=ErrCode.FFMPEG,
            ctx=get_step_ctx(
                {
                    "step": "probe_compilation_segment",
                    "input_path": str(path),
                    "returncode": exc.returncode,
                    "stderr": exc.stderr,
                }
            ),
        ) from exc

    return bool(result.stdout.strip())


def _build_video_filter(segment_count: int) -> str:
    """Build the normalized video concat filter graph."""
    filters = [
        (
            f"[{index}:v:0]"
            "setpts=PTS-STARTPTS,"
            "scale=1920:1080:force_original_aspect_ratio=decrease,"
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
            "setsar=1/1,"
            "fps=60,"
            "format=yuv420p"
            f"[v{index}]"
        )
        for index in range(segment_count)
    ]

    inputs = "".join(f"[v{index}]" for index in range(segment_count))

    filters.append(f"{inputs}concat=n={segment_count}:v=1:a=0[vout]")

    return ";".join(filters)


def _write_manifest(
    segments: list[Segment],
    manifest_path: Path,
) -> None:
    """Write the compilation manifest."""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    manifest_data: list[dict[str, Any]] = [
        {
            "uid": segment.uid,
            "category": segment.category,
            "duration": segment.duration,
            "keywords": segment.keywords,
            "filename": str(segment.output_path),
        }
        for segment in segments
    ]

    with manifest_path.open("w", encoding="utf-8") as file:
        json.dump(
            manifest_data,
            file,
            indent=2,
            ensure_ascii=False,
        )


def make_compilation(
    segments: list[Segment],
    output_path: Path,
    manifest_path: Path | None = None,
    logger: LoggerProtocol | None = None,
) -> None:
    """Generate a video compilation and its optional JSON manifest."""
    logger = ensure_logger(logger, __name__)

    if not segments:
        logger.warning("❌ Aucun segment à compiler.")
        return

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    logger.info(
        "Préparation de la compilation : segments=%d output=%s",
        len(segments),
        output_path,
    )

    segment_paths = [Path(str(segment.output_path)) for segment in segments]

    for segment_path in segment_paths:
        if not segment_path.is_file():
            raise FileNotFoundError(f"Segment introuvable : {segment_path}")

    filter_complex = _build_video_filter(
        segment_count=len(segment_paths),
    )

    job = FFmpegJob(
        step="make_compilation",
        input_path=segment_paths[0],
        additional_inputs=[FFmpegInput(path=path) for path in segment_paths[1:]],
        output_path=output_path,
        filter_complex=filter_complex,
        maps=["[vout]"],
        include_audio=False,
    )

    run_ffmpeg_job(
        job=job,
        logger=logger,
    )

    logger.info(
        "✅ Compilation générée : %s",
        output_path,
    )

    if manifest_path is not None:
        _write_manifest(
            segments=segments,
            manifest_path=manifest_path,
        )

        logger.info(
            "📄 Manifest sauvegardé : %s",
            manifest_path,
        )
