from collections.abc import Mapping
from pathlib import Path
from typing import Any

from shared.models.db_models import Segment  # adapte l'import à ton projet

CONFIDENCE_THRESHOLD = 0.35


def evaluate_video_compliance(metadata: Mapping[str, Any]) -> tuple[str, str]:
    """
    Évalue si un segment respecte la norme interne CutMind.

    Critères :
    - codec_name = hevc
    - profile = Main
    - pix_fmt = yuv420p
    - r_frame_rate = 60/1
    - color_space = bt709
    - color_transfer = bt709
    - color_primaries = bt709
    - codec_tag_string = hvc1
    """
    errors: list[str] = []

    if metadata.get("codec_name") != "hevc":
        errors.append(f"codec incorrect ({metadata.get('codec_name')})")

    if metadata.get("profile") != "Main":
        errors.append(f"profile incorrect ({metadata.get('profile')})")

    if metadata.get("pix_fmt") != "yuv420p":
        errors.append(f"pix_fmt incorrect ({metadata.get('pix_fmt')})")

    if metadata.get("r_frame_rate") != "60/1":
        errors.append(f"fps incorrect ({metadata.get('r_frame_rate')})")

    if metadata.get("color_space") != "bt709":
        errors.append(f"color_space incorrect ({metadata.get('color_space')})")

    color_transfer = metadata.get("color_transfer")
    if color_transfer not in ("bt709", None):
        errors.append(f"color_transfer incorrect ({color_transfer})")

    color_primaries = metadata.get("color_primaries")
    if color_primaries not in ("bt709", None):
        errors.append(f"color_primaries incorrect ({color_primaries})")

    if metadata.get("codec_tag_string") != "hvc1":
        errors.append(f"tag incorrect ({metadata.get('codec_tag_string')})")

    if errors:
        return "error", "Compliance KO : " + ", ".join(errors)

    return "ok", "Segment conforme à la norme CutMind"


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
