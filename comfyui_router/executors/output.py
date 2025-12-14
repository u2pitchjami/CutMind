""" """

from __future__ import annotations

from pathlib import Path
import time

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx


def _is_stable(path: Path, stable_time: int, interval: int) -> bool:
    """
    Vrai si la taille du fichier reste stable pendant stable_time secondes.
    """
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
                last_size = size

            time.sleep(interval)

        return True

    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue dans is_stable().",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"path": str(path)}),
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
        ) from exc
