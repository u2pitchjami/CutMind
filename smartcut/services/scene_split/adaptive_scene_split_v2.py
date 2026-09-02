from __future__ import annotations

from time import perf_counter

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.logger import LoggerProtocol, ensure_logger
from smartcut.executors.scene_analysis_executor import analyze_video
from smartcut.services.scene_split.analysis_detector_service import (
    detect_scenes_from_analysis,
)
from smartcut.services.scene_split.analysis_refiner_service import (
    refine_long_segments,
)
from smartcut.services.scene_split.gap_service import (
    fill_missing_segments,
)


def adaptive_scene_split_v2(
    video_path: str,
    *,
    duration: float,
    initial_threshold: int,
    min_threshold: int,
    threshold_step: int,
    min_duration: float,
    max_duration: float,
    downscale_factor: int,
    logger: LoggerProtocol | None = None,
) -> list[tuple[float, float]]:
    """
    Découpe adaptativement une vidéo à partir d'une seule analyse
    PySceneDetect complète.

    Contrairement à la V1, les raffinements successifs sont effectués
    uniquement à partir des métriques conservées en RAM.

    Args:
        video_path: Chemin vers la vidéo source.
        duration: Durée attendue de la vidéo en secondes.
        initial_threshold: Seuil initial ContentDetector.
        min_threshold: Seuil minimal autorisé.
        threshold_step: Pas de diminution du seuil.
        min_duration: Durée minimale souhaitée d'un segment.
        max_duration: Durée maximale souhaitée d'un segment.
        downscale_factor: Facteur de réduction utilisé pendant
            l'unique analyse vidéo.
        logger: Logger optionnel.

    Returns:
        Liste triée de segments sous forme (start, end), en secondes.

    Raises:
        CutMindError: Si l'analyse ou la construction des scènes échoue.
    """
    logger = ensure_logger(logger, __name__)

    try:
        _validate_parameters(
            duration=duration,
            initial_threshold=initial_threshold,
            min_threshold=min_threshold,
            threshold_step=threshold_step,
            min_duration=min_duration,
            max_duration=max_duration,
            downscale_factor=downscale_factor,
        )

        total_start = perf_counter()

        #
        # 1. UNIQUE ACCÈS À LA VIDÉO
        #
        analysis_start = perf_counter()

        analysis = analyze_video(
            video_path,
            downscale=downscale_factor,
        )

        analysis_elapsed = perf_counter() - analysis_start

        logger.info(
            ("Analyse vidéo V2 terminée en %.2f s (duration=%.2f s, fps=%.3f, frames=%d, downscale=%d)"),
            analysis_elapsed,
            analysis.duration,
            analysis.fps,
            analysis.frame_count,
            downscale_factor,
        )

        #
        # 2. DÉTECTION INITIALE EN RAM
        #
        initial_start = perf_counter()

        scenes = detect_scenes_from_analysis(
            analysis,
            threshold=initial_threshold,
            min_duration=min_duration,
        )

        initial_elapsed = perf_counter() - initial_start

        logger.info(
            "Détection initiale RAM terminée en %.3f s : %d scènes",
            initial_elapsed,
            len(scenes),
        )

        #
        # Si aucune coupure n'est trouvée, on considère toute
        # la vidéo comme un segment de départ.
        #
        if not scenes:
            scenes = [
                (
                    0.0,
                    min(duration, analysis.duration),
                )
            ]

        #
        # 3. CONSTRUCTION DES SEUILS ADAPTATIFS
        #
        thresholds = _build_thresholds(
            initial_threshold=initial_threshold,
            min_threshold=min_threshold,
            threshold_step=threshold_step,
        )

        logger.debug(
            "Seuils de raffinement V2 : %s",
            thresholds,
        )

        #
        # 4. PREMIER RAFFINAGE — UNIQUEMENT EN RAM
        #
        refinement_start = perf_counter()

        refined = refine_long_segments(
            analysis=analysis,
            scenes=scenes,
            thresholds=thresholds,
            min_duration=min_duration,
            max_duration=max_duration,
            logger=logger,
        )

        first_refinement_elapsed = perf_counter() - refinement_start

        logger.info(
            "Premier raffinage RAM terminé en %.3f s : %d segments",
            first_refinement_elapsed,
            len(refined),
        )

        #
        # 5. COMBLER LES ÉVENTUELS TROUS
        #
        refined = fill_missing_segments(
            refined,
            duration,
        )

        #
        # 6. SECOND RAFFINAGE — TOUJOURS EN RAM
        #
        second_refinement_start = perf_counter()

        refined = refine_long_segments(
            analysis=analysis,
            scenes=refined,
            thresholds=thresholds,
            min_duration=min_duration,
            max_duration=max_duration,
            logger=logger,
        )

        second_refinement_elapsed = perf_counter() - second_refinement_start

        logger.info(
            "Second raffinage RAM terminé en %.3f s : %d segments",
            second_refinement_elapsed,
            len(refined),
        )

        #
        # 7. NETTOYAGE FINAL
        #
        refined = [segment for segment in refined if (segment[1] - segment[0]) >= min_duration]

        refined = sorted(
            refined,
            key=lambda segment: segment[0],
        )

        covered = sum(end - start for start, end in refined)

        coverage_ratio = covered / duration if duration > 0.0 else 0.0

        if covered < 0.8 * duration:
            raise CutMindError(
                "La détection des scènes ne couvre pas suffisamment la vidéo.",
                code=ErrCode.UNEXPECTED,
                ctx=get_step_ctx(
                    {
                        "video_path": video_path,
                        "video_duration": duration,
                        "covered_duration": covered,
                        "coverage_ratio": coverage_ratio,
                        "segments": len(refined),
                    }
                ),
            )

        total_elapsed = perf_counter() - total_start

        logger.info(
            ("Découpage adaptatif V2 terminé en %.2f s : %d segments, couverture=%.2f%%"),
            total_elapsed,
            len(refined),
            coverage_ratio * 100.0,
        )

        return refined

    except CutMindError as err:
        raise err.with_context(
            get_step_ctx(
                {
                    "video_path": video_path,
                    "initial_threshold": initial_threshold,
                    "min_threshold": min_threshold,
                    "min_duration": min_duration,
                    "max_duration": max_duration,
                    "downscale_factor": downscale_factor,
                }
            )
        ) from err

    except Exception as exc:
        raise CutMindError(
            "Erreur inattendue pendant le découpage adaptatif V2.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx(
                {
                    "video_path": video_path,
                    "type": type(exc).__name__,
                    "internal_error": str(exc),
                }
            ),
        ) from exc


def _build_thresholds(
    *,
    initial_threshold: int,
    min_threshold: int,
    threshold_step: int,
) -> list[int]:
    """Construit les seuils de raffinement sous le seuil initial."""
    return list(
        range(
            initial_threshold - threshold_step,
            min_threshold - 1,
            -threshold_step,
        )
    )


def _validate_parameters(
    *,
    duration: float,
    initial_threshold: int,
    min_threshold: int,
    threshold_step: int,
    min_duration: float,
    max_duration: float,
    downscale_factor: int,
) -> None:
    """Valide les paramètres du découpage adaptatif."""
    if duration <= 0.0:
        raise ValueError("duration doit être > 0")

    if initial_threshold <= 0:
        raise ValueError("initial_threshold doit être > 0")

    if min_threshold <= 0:
        raise ValueError("min_threshold doit être > 0")

    if min_threshold >= initial_threshold:
        raise ValueError("min_threshold doit être inférieur à initial_threshold")

    if threshold_step <= 0:
        raise ValueError("threshold_step doit être > 0")

    if min_duration <= 0.0:
        raise ValueError("min_duration doit être > 0")

    if max_duration <= min_duration:
        raise ValueError("max_duration doit être supérieur à min_duration")

    if downscale_factor < 1:
        raise ValueError("downscale_factor doit être >= 1")
