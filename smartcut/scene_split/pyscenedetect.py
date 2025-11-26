""" """

from __future__ import annotations

from scenedetect import ContentDetector, FrameTimecode, SceneManager, VideoManager  # type: ignore

from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger


@with_child_logger
def detect_scenes_with_pyscenedetect(
    video_path: str,
    threshold: float = 30.0,
    min_scene_len: int = 15,
    start: float | None = None,
    end: float | None = None,
    downscale_factor: int = 1,
    logger: LoggerProtocol | None = None,
) -> list[tuple[float, float]]:
    """
    Détection PySceneDetect sur une vidéo entière ou un intervalle spécifique (start/end en secondes).
    """
    logger = ensure_logger(logger, __name__)
    video_manager = VideoManager([video_path])
    video_manager.set_downscale_factor(downscale_factor)
    scene_manager = SceneManager()
    min_scene: int = int(min_scene_len)
    scene_manager.add_detector(ContentDetector(threshold=threshold, min_scene_len=min_scene))

    start_tc = FrameTimecode(timecode=start, fps=video_manager.frame_rate) if start else None
    end_tc = FrameTimecode(timecode=end, fps=video_manager.frame_rate) if end else None

    if start_tc:
        video_manager.seek(start_tc)

    logger.debug(f"detect_scenes_with_pyscenedetect : Scenes detection: {start_tc} - {end_tc}")
    # Détection de scènes
    scene_manager.detect_scenes(video_manager, end_time=end_tc)
    scenes = scene_manager.get_scene_list()

    # Filtrage manuel pour compatibilité <0.6
    filtered = []
    for s, e in scenes:
        s_sec, e_sec = s.get_seconds(), e.get_seconds()
        if start and e_sec <= start:
            continue
        if end and s_sec >= end:
            continue
        filtered.append((max(s_sec, start or 0.0), min(e_sec, end or e_sec)))
    logger.debug(f"detect_scenes_with_pyscenedetect : Scenes detected: {len(filtered)}scenes --> {filtered}")
    return filtered


@with_child_logger
def fill_missing_segments(
    scenes: list[tuple[float, float]], video_duration: float, logger: LoggerProtocol | None = None
) -> list[tuple[float, float]]:
    """
    Ajoute des segments virtuels pour combler les zones sans détection.
    """
    logger = ensure_logger(logger, __name__)
    if not scenes:
        return [(0.0, video_duration)]

    # On trie et nettoie les doublons
    scenes = sorted(set(scenes), key=lambda x: x[0])
    filled = []

    # Premier gap avant la première scène
    if scenes[0][0] > 0.5:  # léger offset pour éviter les micro-décalages
        filled.append((0.0, scenes[0][0]))

    # Gaps entre scènes
    for i in range(len(scenes) - 1):
        end_current = scenes[i][1]
        start_next = scenes[i + 1][0]
        gap = start_next - end_current
        if gap > 0.5:  # avant 1.0s → on descend à 0.5s
            filled.append((end_current, start_next))

    # Gap après la dernière scène
    if video_duration - scenes[-1][1] > 0.5:
        filled.append((scenes[-1][1], video_duration))

    if filled:
        logger.debug(f"🧩 {len(filled)} gaps détectés et ajoutés à la liste.")
    else:
        logger.debug("✅ Aucun gap détecté (vidéo couverte en continu).")

    # On fusionne et on re-trie le tout
    all_segments = sorted(scenes + filled, key=lambda x: x[0])
    return all_segments


@with_child_logger
def refine_long_segments(
    video_path: str,
    scenes: list[tuple[float, float]],
    thresholds: list[float],
    min_duration: float = 5.0,
    max_duration: float = 180.0,
    logger: LoggerProtocol | None = None,
) -> list[tuple[float, float]]:
    """
    Raffine les segments trop longs (ou proches du max) via descente de seuil dynamique.
    """
    logger = ensure_logger(logger, __name__)
    refined: list[tuple[float, float]] = []

    for start, end in scenes:
        duration = end - start

        # court → on garde
        if duration < 0.8 * max_duration:
            refined.append((start, end))
            continue

        th = thresholds[0] if thresholds else 30
        logger.debug(f"🔁 Raffinage local {start:.1f}s–{end:.1f}s (durée {duration:.1f}s, th={th})")

        # boucle descendante jusqu’à obtenir une coupure
        sub_scenes = []
        for t in thresholds:
            sub_scenes = detect_scenes_with_pyscenedetect(video_path, threshold=t, start=start, end=end, logger=logger)
            if sub_scenes:
                logger.debug(f"🪓 {len(sub_scenes)} sous-segments trouvés à th={t}")
                break

        # rien trouvé à aucun seuil → on garde le segment brut
        if not sub_scenes:
            logger.debug(f"⚠️ Aucun découpage trouvé sur {start:.1f}-{end:.1f}s → conservé.")
            refined.append((start, end))
            continue

        # sous-segments trouvés → éventuel raffinement récursif
        for s, e in sub_scenes:
            if (e - s) > max_duration and len(thresholds) > 1:
                refined.extend(refine_long_segments(video_path, [(s, e)], thresholds[1:], min_duration, max_duration))
            else:
                refined.append((s, e))

    return sorted(refined, key=lambda x: x[0])
