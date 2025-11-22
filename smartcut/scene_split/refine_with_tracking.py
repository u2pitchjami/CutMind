from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

from shared.utils.config import JSON_PYSCENE
from shared.utils.logger import LoggerProtocol, ensure_logger
from smartcut.models_sc.smartcut_model import SmartCutSession
from smartcut.scene_split.pyscenedetect import refine_long_segments


def refine_with_tracking(
    session: SmartCutSession,
    initial_scenes: list[tuple[float, float]],
    thresholds: list[float],
    min_duration: float = 15.0,
    max_duration: float = 180.0,
    logger: LoggerProtocol | None = None,
) -> list[tuple[float, float]]:
    """
    Wrapper autour de refine_long_segments avec tracking de l'état dans un fichier JSON.
    Ne modifie pas le comportement de base.
    """
    logger = ensure_logger(logger, __name__)
    json_path = Path(JSON_PYSCENE) / f"{session.video_name}.scenedetect.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)

    # Initialisation de l'état
    if json_path.exists():
        logger.warning("💾 Fichier d'état déjà existant (pas rechargé dans cette version).")
        with open(json_path) as f:
            state = json.load(f)
        pending = state.get("pending", [])
        done = state.get("done", [])
    else:
        pending = initial_scenes
        done = []

    # Traitement avec suivi
    refined: list[tuple[float, float]] = []

    while pending:
        start, end = pending.pop(0)
        logger.debug(f"🔁 Raffinage tracké {start:.1f}s–{end:.1f}s")

        new_segments = refine_long_segments(
            video_path=session.video,
            scenes=[(start, end)],
            thresholds=thresholds,
            min_duration=min_duration,
            max_duration=max_duration,
            logger=logger,
        )

        for s, e in new_segments:
            if (e - s) > max_duration and len(thresholds) > 1:
                pending.append((s, e))  # à retraiter
            else:
                refined.append((s, e))  # validé

        # Mise à jour JSON
        done.extend(refined)
        save_data = {
            "uid": session.uid,
            "video": session.video,
            "thresholds": thresholds,
            "done": done,
            "pending": pending,
            "updated_at": datetime.now().isoformat(),
        }

        with open(json_path, "w") as f:
            json.dump(save_data, f, indent=2)

    return sorted(refined, key=lambda x: x[0])
