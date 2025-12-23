""" """

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shared.executors.ffmpeg_utils import get_fps, get_resolution
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.config import WORKFLOW_MAP


def route_workflow(video_path: Path) -> Path | None:
    """
    Retourne le chemin du workflow à utiliser selon la hauteur de la vidéo.
    """
    try:
        _, height = get_resolution(video_path)
        fps = get_fps(video_path)
        if height == 2160:
            return WORKFLOW_MAP["2160p"]
        if height == 1080:
            return WORKFLOW_MAP["1080p"]
        if height == 720:
            if fps < 60:
                return WORKFLOW_MAP["720p"]
            else:
                return WORKFLOW_MAP["720p_nofps"]
        if height in [360, 480, 240]:
            return WORKFLOW_MAP["Autres"]
        return None
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors du choix du workflow Comfyui.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video_path": str(video_path)}),
        ) from exc


def load_workflow(path: Path) -> Any:
    """
    Charge le workflow ComfyUI depuis un fichier JSON.
    """
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors du chargement du workflow Comfyui.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"path": str(path)}),
        ) from exc


def optimal_batch_size(total_frames: int, min_size: int = 60, max_size: int = 80) -> int:
    """
    Calcule la taille de batch optimale pour répartir les frames sans batch final trop petit.
    """
    # if total_frames <= 0:
    #     raise ValueError("Le nombre total de frames doit être positif.")

    best_size = min_size
    smallest_remainder = total_frames

    try:
        for size in range(min_size, max_size + 1):
            remainder = total_frames % size

            # Évite les batchs finaux trop petits (< 60 % du batch)
            if remainder != 0 and remainder < (size * 0.6):
                continue

            if remainder < smallest_remainder:
                smallest_remainder = remainder
                best_size = size
        return best_size
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors du optimal_batch_size.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx(),
        ) from exc


def inject_video_path(workflow: dict[str, Any], video_path: Path, frames_per_batch: int) -> dict[str, Any]:
    """
    Injecte dynamiquement le chemin de la vidéo source et le nom de fichier dans les nœuds ComfyUI VHS_LoadVideoPath et
    VHS_VideoCombine (nouveau format API).

    Args:
        workflow: dict JSON du flow ComfyUI.
        video_path: chemin local vers la vidéo source à injecter.

    Returns:
        Workflow modifié avec les bons chemins injectés.
    """
    filename_only = video_path.stem
    container_path = str(video_path)
    try:
        if "nodes" in workflow:
            nodes = workflow["nodes"]
        else:
            # format style "export to API" ou "workflow_api.json"
            nodes = [{"id": int(k), **v} for k, v in workflow.items() if isinstance(v, dict) and "class_type" in v]

        for node in nodes:
            # node_id = node.get("id")  # utile seulement si tu as ajouté l'ID comme montré précédemment
            node_type = node.get("class_type")  # ✅ On lit class_type au lieu de type
            inputs = node.get("inputs", {})

            # 📥 Injection dans VHS_BatchManager
            if node_type == "VHS_BatchManager":
                if "frames_per_batch" in inputs:
                    inputs["frames_per_batch"] = frames_per_batch

            # 📥 Injection dans VHS_LoadVideoPath
            if node_type == "VHS_LoadVideoPath":
                if "video" in inputs:
                    inputs["video"] = container_path

            # 📼 Injection dans VHS_VideoCombine
            elif node_type == "VHS_VideoCombine":
                if "filename_prefix" in inputs:
                    inputs["filename_prefix"] = filename_only

            # 🛠️ Correction éventuelle class_type manquant
            if "type" in node and "class_type" not in node:
                node["class_type"] = node["type"]

        # # 🧩 Ajout d'un output s'il manque
        # if "output" not in workflow:
        #     workflow["output"] = [["44", 0]]
        #     logger.info("📌 Ajout de l'output (node ID 44, slot 0)")

        return workflow
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors de la modif du workflow Comfyui.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"video_path": str(video_path)}),
        ) from exc
