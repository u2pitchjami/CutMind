""" """

from __future__ import annotations

from pathlib import Path
import time

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx


def _is_stable(path: Path, stable_time: int, check_interval: int) -> bool:
    """
    Vérifie que la taille d'un fichier reste stable pendant un certain temps.
    """
    last_size = -1
    stable_duration = 0
    try:
        while stable_duration < stable_time:
            if not path.exists():
                return False

            current_size = path.stat().st_size
            if current_size == last_size:
                stable_duration += check_interval
            else:
                stable_duration = 0
                last_size = current_size

            time.sleep(check_interval)

        return True
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors du is_stable.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"path": path}),
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
