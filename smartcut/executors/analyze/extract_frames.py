""" """

from __future__ import annotations

import os

import cv2

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.config import TMP_FRAMES_DIR_SC
from smartcut.executors.analyze.analyze_utils import compute_num_frames


def extract_segment_frames(
    cap: cv2.VideoCapture,
    video_name: str,
    start: float,
    end: float,
    auto_frames: bool,
    fps_extract: float,
    base_rate: int,
) -> list[str]:
    """
    extract_segment_frames _summary_

    _extended_summary_

    Args:
        cap (cv2.VideoCapture): _description_
        video_name (str): _description_
        start (float): _description_
        end (float): _description_
        auto_frames (bool): _description_
        fps_extract (float): _description_
        base_rate (int): _description_

    Returns:
        list[str]: _description_
    """
    try:
        seg_duration = end - start

        num_frames = compute_num_frames(seg_duration, base_rate) if auto_frames else int(seg_duration * fps_extract)
        num_frames = max(1, num_frames)

        timestamps = [start + (seg_duration / num_frames) * i for i in range(num_frames)]
        frame_paths: list[str] = []

        for t in timestamps:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ret, frame = cap.read()
            if not ret:
                continue

            path = os.path.join(
                TMP_FRAMES_DIR_SC,
                f"{video_name}_seg_{int(start * 10)}_{int(end * 10)}_{int(t * 10)}.jpg",
            )
            cv2.imwrite(path, frame)
            frame_paths.append(path)

        return frame_paths
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors de la suppression des frames.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"path": str(path), "name": video_name}),
        ) from exc
