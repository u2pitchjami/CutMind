""" """

from __future__ import annotations

import os

from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from shared.utils.settings import get_settings
from smartcut.analyze.analyze_core import analyze_by_segments
from smartcut.models_sc.smartcut_model import SmartCutSession

settings = get_settings()

FPS_EXTRACT = settings.analyse_segment.fps_extract
BASE_RATE = settings.analyse_segment.base_rate


@with_child_logger
def analyze_video_segments(
    video_path: str,
    session: SmartCutSession,
    frames_per_segment: int = 3,
    auto_frames: bool = True,
    lite: bool = False,
    logger: LoggerProtocol | None = None,
) -> SmartCutSession:
    """
    Segmented video analysis with optional SmartCut session tracking.

    Each segment is analyzed independently (vision + reasoning). If combine=True, a final global synthesis is generated
    at the end.
    """
    logger = ensure_logger(logger, __name__)

    if lite:
        logger.info(
            f"🟢 Mode LITE — 🎬 Analyse des segments depuis le dossier : \
            {video_path} ({len(session.segments)} detected cuts)"
        )
    else:
        logger.info(f"🔵 Mode COMPLET — 🎬 Analyse de la vidéo : {video_path} ({len(session.segments)} detected cuts)")

    analyze_by_segments(
        video_path=video_path,
        frames_per_segment=frames_per_segment,
        auto_frames=auto_frames,
        fps_extract=FPS_EXTRACT,
        base_rate=BASE_RATE,
        session=session,
        lite=lite,
        logger=logger,
    )
    # logger.debug(f"session : {session}")
    if session is None:
        session = SmartCutSession(
            video=os.path.basename(video_path),
            duration=0.0,
            fps=0.0,
            status="ia_done",
            segments=[],
        )

    return session
