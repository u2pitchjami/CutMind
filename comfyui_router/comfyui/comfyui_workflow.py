from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from comfyui_router.ffmpeg.ffmpeg_command import get_resolution
from comfyui_router.utils.config import WORKFLOW_MAP
from comfyui_router.utils.logger import get_logger

logger = get_logger("Comfyui Router")


def route_workflow(video_path: Path) -> Path | None:
    """Retourne le chemin du workflow à utiliser selon la hauteur de la vidéo."""
    _, height = get_resolution(video_path)
    if height >= 1080:
        return WORKFLOW_MAP["1080p"]
    if height == 720:
        return WORKFLOW_MAP["720p"]
    if height in [360, 480]:
        return WORKFLOW_MAP["Autres"]
    return None


def load_workflow(path: Path) -> Any:
    """Charge le workflow ComfyUI depuis un fichier JSON."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def inject_video_path(workflow: dict[str, Any], video_path: Path) -> dict[str, Any]:
    """
    Injecte dynamiquement le chemin de la vidéo source et le nom de fichier
    dans les nœuds ComfyUI VHS_LoadVideoPath et VHS_VideoCombine (nouveau format API).

    Args:
        workflow: dict JSON du flow ComfyUI.
        video_path: chemin local vers la vidéo source à injecter.

    Returns:
        Workflow modifié avec les bons chemins injectés.
    """
    filename_only = video_path.stem
    container_path = str(video_path).replace("/mnt/user/Zin-progress/comfyui-nvidia/basedir", "/basedir")
    if "nodes" in workflow:
        nodes = workflow["nodes"]
    else:
        # format style "export to API" ou "workflow_api.json"
        nodes = [{"id": int(k), **v} for k, v in workflow.items() if isinstance(v, dict) and "class_type" in v]
    logger.info(f"📦 {len(nodes)} nodes dans le workflow")

    for node in nodes:
        node_id = node.get("id")  # utile seulement si tu as ajouté l'ID comme montré précédemment
        node_type = node.get("class_type")  # ✅ On lit class_type au lieu de type
        inputs = node.get("inputs", {})

        # 📥 Injection dans VHS_LoadVideoPath
        if node_type == "VHS_LoadVideoPath":
            if "video" in inputs:
                logger.info(f"✅ Injection chemin vidéo dans node ID {node_id}")
                inputs["video"] = container_path

        # 📼 Injection dans VHS_VideoCombine
        elif node_type == "VHS_VideoCombine":
            if "filename_prefix" in inputs:
                logger.info(f"✅ Injection nom fichier dans node ID {node_id}")
                inputs["filename_prefix"] = filename_only

        # 🛠️ Correction éventuelle class_type manquant
        if "type" in node and "class_type" not in node:
            node["class_type"] = node["type"]

    # # 🧩 Ajout d'un output s'il manque
    # if "output" not in workflow:
    #     workflow["output"] = [["44", 0]]
    #     logger.info("📌 Ajout de l'output (node ID 44, slot 0)")

    logger.debug(f"workflow : {workflow}")
    return workflow
