from __future__ import annotations

import os
from pathlib import Path

import cv2

from shared.utils.config import BATCH_FRAMES_DIR_SC, MULTIPLE_FRAMES_DIR_SC, TMP_FRAMES_DIR_SC
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from smartcut.analyze.analyze_utils import (
    delete_frames,
)
from smartcut.models_sc.ai_result import AIResult

KeywordsBatches = list[AIResult]


@with_child_logger
def cleanup_temp(logger: LoggerProtocol | None = None) -> None:
    """
    Nettoyage répertoires temporaires
    """
    logger = ensure_logger(logger, __name__)
    for path in [TMP_FRAMES_DIR_SC, MULTIPLE_FRAMES_DIR_SC, BATCH_FRAMES_DIR_SC]:
        delete_frames(Path(path), logger=logger)
    os.makedirs(TMP_FRAMES_DIR_SC, exist_ok=True)


@with_child_logger
def open_vid(video_path: str, logger: LoggerProtocol | None = None) -> tuple[cv2.VideoCapture, str]:
    # --- Ouverture vidéo
    logger = ensure_logger(logger, __name__)
    video_name = Path(video_path).stem
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.error(f"Impossible d'ouvrir la vidéo {video_path}")
        raise
    return cap, video_name


def release_cap(cap: cv2.VideoCapture) -> None:
    cap.release()
