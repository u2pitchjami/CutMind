""" """

from __future__ import annotations

from pathlib import Path
import time

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.logger import LoggerProtocol, ensure_logger


def _is_stable(path: Path, stable_time: int, interval: int, logger: LoggerProtocol | None = None) -> bool:
    """
    Vrai si la taille du fichier reste stable pendant stable_time secondes.
    """
    logger = ensure_logger(logger, __name__)
    try:
        last_size = -1
        stable_elapsed = 0

        while stable_elapsed < stable_time:
            if not path.exists():
                return False

            size = path.stat().st_size

            if size == last_size:
                stable_elapsed += interval
            else:
                stable_elapsed = 0
                delta = size - last_size
                last_size = size
                growth_mb = delta / 1024 / 1024
                logger.info(f"📈 Croissance détectée : +{growth_mb:.2f} MB")

            time.sleep(interval)

        return True

    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue dans is_stable().",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"path": str(path)}),
            original_exception=exc,
        ) from exc


def cleanup_outputs(base_stem: str, keep: Path, output_dir: Path) -> None:
    """
    Supprime les fichiers intermédiaires de ComfyUI (png, mp4 sans audio, etc.) sauf le fichier final.
    """
    try:
        patterns = [
            f"{base_stem}_*.png",
            f"{base_stem}_*.mp4",
        ]
        for pattern in patterns:
            for file in output_dir.glob(pattern):
                if file.resolve() != keep.resolve():
                    file.unlink()
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors de la suppression du fichier.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"base_stem": base_stem}),
            original_exception=exc,
        ) from exc
