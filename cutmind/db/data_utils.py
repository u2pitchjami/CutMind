"""
conversion de data pour insertion en base
"""

from __future__ import annotations

from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger


@with_child_logger
def format_resolution(res: tuple[int, int] | None, logger: LoggerProtocol | None = None) -> str | None:
    """
    Convertit une résolution (tuple) en chaîne 'WxH'.
    Retourne None si invalide ou vide.
    """
    logger = ensure_logger(logger, __name__)
    try:
        if not res or not all(isinstance(x, int) and x > 0 for x in res):
            return None
        return f"{res[0]}x{res[1]}"
    except Exception as err:  # pylint: disable=broad-except
        logger.warning("⚠️ format_resolution: %s", err)
        return None
