from __future__ import annotations

import os
from pathlib import Path

import cv2

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.config import BATCH_FRAMES_DIR_SC, MULTIPLE_FRAMES_DIR_SC, TMP_FRAMES_DIR_SC
from smartcut.executors.analyze.analyze_utils import delete_frames
from smartcut.models_sc.ai_result import AIResult

KeywordsBatches = list[AIResult]


def cleanup_temp() -> None:
    """
    Nettoyage répertoires temporaires
    """
    try:
        for path in [TMP_FRAMES_DIR_SC, MULTIPLE_FRAMES_DIR_SC, BATCH_FRAMES_DIR_SC]:
            delete_frames(Path(path))
        os.makedirs(TMP_FRAMES_DIR_SC, exist_ok=True)
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur lors de la suppression des répertoires temp.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"path": path}),
        ) from exc


def open_vid(video_path: str) -> tuple[cv2.VideoCapture, str]:
    # --- Ouverture vidéo
    video_name = Path(video_path).stem
    try:
        cap = cv2.VideoCapture(video_path)
    except Exception as exc:
        raise CutMindError(
            "❌ Impossible d'ouvrir la vidéo.",
            code=ErrCode.VIDEO,
            ctx=get_step_ctx({"path": str(video_path), "name": video_name}),
        ) from exc
    return cap, video_name


def release_cap(cap: cv2.VideoCapture) -> None:
    try:
        cap.release()
    except Exception as exc:
        raise CutMindError(
            "❌ Impossible lors de la fermeture de la vidéo.",
            code=ErrCode.VIDEO,
            ctx=get_step_ctx({"cap": cap}),
        ) from exc
