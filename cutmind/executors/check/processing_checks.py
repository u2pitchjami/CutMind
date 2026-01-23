from pathlib import Path

from cutmind.models_cm.db_models import Segment  # adapte l'import à ton projet

CONFIDENCE_THRESHOLD = 0.35


def evaluate_scene_detection_output(success: bool, nb_scenes: int) -> tuple[str, str]:
    if not success:
        return "error", "Échec analyse pyscenedetect"
    if nb_scenes == 0:
        return "partial", "Aucune scène détectée"
    return "ok", f"{nb_scenes} scènes détectées"


def evaluate_segment_cut(expected: Path) -> tuple[str, str]:
    if expected.exists():
        return "ok", f"{expected} segment généré"
    else:
        return "error", "segment non généré"


def evaluate_segment_move(output_path: str, basedir: str) -> tuple[str, str]:
    import os

    if os.path.abspath(output_path).startswith(os.path.abspath(basedir)):
        return "ok", "Fichier déplacé dans CUTMIND_BASEDIR"
    return "error", "Fichier en dehors du dossier cible"


def evaluate_comfyui_output(fps: float | None, resolution: str | None) -> tuple[str, str]:
    """
    Évalue si le segment est passé correctement par le flow ComfyUI.
    Critères :
    - fps doit être exactement 60
    - résolution doit être '1920x1080' ou '3840x2160'
    """
    errors = []

    if fps != 60:
        errors.append(f"fps incorrect ({fps})")

    if resolution not in ("1920x1080", "3840x2160"):
        errors.append(f"résolution non conforme ({resolution})")

    if errors:
        return "error", "ComfyUI KO : " + ", ".join(errors)

    return "ok", f"FPS = {fps}, Résolution = {resolution}"


def evaluate_ia_output(segment: Segment) -> tuple[str, str]:
    score = sum(
        [
            bool(segment.category),
            bool(segment.description and len(segment.description) > 30),
            bool(segment.keywords and len(segment.keywords) >= 3),
        ]
    )
    if score == 3:
        return "ok", "IA complète"
    elif score == 0:
        return "ko", "IA sans sortie exploitable"
    else:
        return "partial", "IA partiellement remplie"


def evaluate_confidence_output(score: float) -> tuple[str, str]:
    if score is None:
        return "error", "Aucun score de confiance"
    elif score == 0.0:
        return "partial", "Score de confiance nul"
    elif score < CONFIDENCE_THRESHOLD:
        return "partial", f"Confiance trop faible ({score:.2f})"
    return "ok", f"Confiance = {score:.2f}"
