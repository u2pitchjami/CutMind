from __future__ import annotations

from pathlib import Path
import subprocess

from shared.utils.logger import LoggerProtocol, ensure_logger
from shared.utils.settings import get_settings


class RealEsrganError(RuntimeError):
    """Raised when Real-ESRGAN processing fails."""


def upscale_frames_with_realesrgan(
    input_dir: Path,
    output_dir: Path,
    upscale_factor: int,
    realesrgan_bin: Path,
    model_dir: Path,
    model_name: str,
    logger: LoggerProtocol | None = None,
) -> Path:
    """Upscale image frames with realesrgan-ncnn-vulkan."""

    logger = ensure_logger(logger, __name__)
    settings = get_settings()
    G_PARAM = settings.router_processor.g_param
    J_PARAM = settings.router_processor.j_param
    if not input_dir.exists():
        raise FileNotFoundError(f"Frames input directory not found: {input_dir}")

    if upscale_factor <= 1:
        logger.info("Upscale non nécessaire, réutilisation de : %s", input_dir)
        return input_dir

    output_dir.mkdir(parents=True, exist_ok=True)

    command = [
        str(realesrgan_bin),
        "-i",
        str(input_dir),
        "-o",
        str(output_dir),
        "-n",
        model_name,
        "-m",
        str(model_dir),
        "-s",
        str(upscale_factor),
        "-g",
        str(G_PARAM),
        "-j",
        str(J_PARAM),
    ]

    logger.info(
        "Real-ESRGAN | input=%s | output=%s | model=%s | scale=x%s",
        input_dir,
        output_dir,
        model_name,
        upscale_factor,
    )

    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=False,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RealEsrganError(f"Binaire Real-ESRGAN introuvable : {realesrgan_bin}") from exc
    except subprocess.CalledProcessError as exc:
        logger.error("Real-ESRGAN stdout: %s", exc.stdout)
        logger.error("Real-ESRGAN stderr: %s", exc.stderr)
        raise RealEsrganError(f"Real-ESRGAN a échoué avec le code {exc.returncode}") from exc

    if result.stdout:
        logger.debug("Real-ESRGAN stdout: %s", result.stdout)

    if result.stderr:
        logger.debug("Real-ESRGAN stderr: %s", result.stderr)

    if not any(output_dir.iterdir()):
        raise RealEsrganError(f"Real-ESRGAN terminé mais aucun fichier généré dans : {output_dir}")

    logger.info("✅ Upscale Real-ESRGAN terminé : %s", output_dir)

    return output_dir
