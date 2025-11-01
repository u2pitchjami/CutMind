""" """

from __future__ import annotations

import os

import cv2

from shared.utils.config import TMP_FRAMES_DIR_SC
from shared.utils.logger import get_logger
from smartcut.analyze.analyze_utils import compute_num_frames

logger = get_logger(__name__)


def extract_segment_frames(
    cap: cv2.VideoCapture,
    video_name: str,
    start: float,
    end: float,
    auto_frames: bool,
    fps_extract: float,
    base_rate: int,
) -> list[str]:
    seg_duration = end - start
    logger.debug(f"Segment {start:.2f}s → {end:.2f}s | durée : {seg_duration:.2f}s")

    num_frames = compute_num_frames(seg_duration, base_rate) if auto_frames else int(seg_duration * fps_extract)
    num_frames = max(1, num_frames)
    logger.debug(f"Nombre de frames à extraire : {num_frames}")

    timestamps = [start + (seg_duration / num_frames) * i for i in range(num_frames)]
    frame_paths: list[str] = []

    for t in timestamps:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ret, frame = cap.read()
        if not ret:
            logger.warning(f"⚠️ Impossible de lire la frame à {t:.2f}s")
            continue

        path = os.path.join(
            TMP_FRAMES_DIR_SC,
            f"{video_name}_seg_{int(start * 10)}_{int(end * 10)}_{int(t * 10)}.jpg",
        )
        cv2.imwrite(path, frame)
        frame_paths.append(path)

    logger.info(f"🎞️ Segment {start:.1f}s → {end:.1f}s : {len(frame_paths)} frames extraites.")
    return frame_paths
