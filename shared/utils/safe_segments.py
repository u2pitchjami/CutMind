from collections.abc import Callable, Iterable
from functools import wraps
from pathlib import Path
from typing import Any

from cutmind.models_cm.db_models import Segment, Video
from shared.utils.fs import safe_file_check
from shared.utils.logger import LoggerProtocol, ensure_logger


def safe_segments(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Décorateur : vérifie automatiquement les fichiers des segments.

    Compatible avec :
      - un Segment unique
      - une liste/tuple de segments
      - un Video contenant .segments
      - un iterable quelconque de segments
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        logger: LoggerProtocol | None = kwargs.get("logger")
        logger = ensure_logger(logger, func.__module__)

        # Fonction utilitaire locale
        def validate_item(item: Any) -> None:
            if isinstance(item, Segment):
                if not item.output_path:
                    raise RuntimeError(f"Segment sans output_path : {item.uid}")
                safe_file_check(Path(item.output_path))
            elif isinstance(item, Video):
                for seg in item.segments:
                    validate_item(seg)
            elif isinstance(item, Iterable) and not isinstance(item, (str | bytes)):
                for sub in item:
                    validate_item(sub)

        # Vérifie tous les arguments (args + kwargs)
        for arg in args:
            validate_item(arg)
        for arg in kwargs.values():
            validate_item(arg)

        # Tous les fichiers sont safe → exécution réelle
        return func(*args, **kwargs)

    return wrapper
