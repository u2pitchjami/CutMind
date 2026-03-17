from __future__ import annotations

import traceback

from shared.utils.logger import LoggerProtocol


def log_exception(logger: LoggerProtocol, exc: Exception) -> None:
    logger.error(
        "".join(
            traceback.format_exception(
                exc.__class__,
                exc,
                exc.__traceback__,
            )
        )
    )
