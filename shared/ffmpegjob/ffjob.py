""" """

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import subprocess

from shared.ffmpegjob.ffmpeg_settings import FFmpegExportSettings
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.logger import LoggerProtocol, ensure_logger


@dataclass(slots=True, frozen=True)
class FFmpegJob:
    step: str
    input_path: Path
    output_path: Path
    include_audio: bool = True
    audio_args: list[str] | None = None
    video_filters: list[str] = field(default_factory=list)
    input_args: list[str] = field(default_factory=list)
    output_args: list[str] = field(default_factory=list)
    use_common_video_args: bool = True


def build_ffmpeg_cmd(job: FFmpegJob, cfg: FFmpegExportSettings) -> list[str]:
    cmd: list[str] = [
        "ffmpeg",
        "-y",
        *job.input_args,
        "-i",
        str(job.input_path),
    ]

    if job.video_filters:
        cmd.extend(["-vf", ",".join(job.video_filters)])

    if job.use_common_video_args:
        cmd.extend(cfg.video_args())

    if job.include_audio:
        if job.audio_args is not None:
            cmd.extend(job.audio_args)
        else:
            cmd.extend(cfg.audio_args())
    else:
        cmd.append("-an")

    cmd.extend(job.output_args)
    cmd.append(str(job.output_path))

    return cmd


def run_ffmpeg_job(
    job: FFmpegJob,
    logger: LoggerProtocol | None = None,
) -> Path:
    logger = ensure_logger(logger, __name__)
    cfg = FFmpegExportSettings.from_settings()

    job.output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = build_ffmpeg_cmd(job, cfg)

    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )
        return job.output_path

    except subprocess.CalledProcessError as exc:
        logger.error(
            "FFmpeg failed. step=%s returncode=%s stderr=%s",
            job.step,
            exc.returncode,
            exc.stderr,
        )
        raise CutMindError(
            f"❌ Erreur FFmpeg pendant l'étape : {job.step}",
            code=ErrCode.FFMPEG,
            ctx=get_step_ctx(
                {
                    "step": job.step,
                    "input_path": str(job.input_path),
                    "output_path": str(job.output_path),
                    "returncode": exc.returncode,
                    "stderr": exc.stderr,
                }
            ),
        ) from exc
