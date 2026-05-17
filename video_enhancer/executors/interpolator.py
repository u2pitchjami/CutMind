from __future__ import annotations

from pathlib import Path
import subprocess

from shared.utils.logger import LoggerProtocol, ensure_logger
from shared.utils.settings import get_settings


class RifeError(RuntimeError):
    """Raised when RIFE processing fails."""


def interpolate_frames_with_rife(
    input_dir: Path,
    output_dir: Path,
    rife_bin: Path,
    model_dir: Path,
    passes: int = 1,
    logger: LoggerProtocol | None = None,
) -> Path:
    """Interpolate image frames with rife-ncnn-vulkan."""

    logger = ensure_logger(logger, __name__)
    settings = get_settings()
    G_PARAM = settings.router_processor.g_param
    J_PARAM = settings.router_processor.j_param
    if not input_dir.exists():
        raise FileNotFoundError(f"Frames input directory not found: {input_dir}")

    if passes <= 0:
        logger.info("Interpolation RIFE non nécessaire, réutilisation de : %s", input_dir)
        return input_dir

    current_input_dir = input_dir

    for pass_index in range(1, passes + 1):
        current_output_dir = output_dir / f"pass_{pass_index:02d}"

        current_output_dir.mkdir(parents=True, exist_ok=True)

        command = [
            str(rife_bin),
            "-i",
            str(current_input_dir),
            "-o",
            str(current_output_dir),
            "-m",
            str(model_dir),
            "-g",
            str(G_PARAM),
            "-j",
            str(J_PARAM),
        ]

        logger.info(
            "RIFE | pass=%s/%s | input=%s | output=%s | model=%s",
            pass_index,
            passes,
            current_input_dir,
            current_output_dir,
            model_dir,
        )

        try:
            result = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise RifeError(f"Binaire RIFE introuvable : {rife_bin}") from exc
        except subprocess.CalledProcessError as exc:
            logger.error("RIFE stdout: %s", exc.stdout)
            logger.error("RIFE stderr: %s", exc.stderr)
            raise RifeError(f"RIFE a échoué avec le code {exc.returncode}") from exc

        if result.stdout:
            logger.debug("RIFE stdout: %s", result.stdout)

        if result.stderr:
            logger.debug("RIFE stderr: %s", result.stderr)

        if not any(current_output_dir.iterdir()):
            raise RifeError(f"RIFE terminé mais aucun fichier généré dans : {current_output_dir}")

        current_input_dir = current_output_dir

    logger.info("✅ Interpolation RIFE terminée : %s", current_input_dir)

    return current_input_dir
