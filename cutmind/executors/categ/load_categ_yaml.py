from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from cutmind.models_cm.categ_model import CategoryRule
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx


def load_category_rules(yaml_path: Path) -> list[CategoryRule]:
    """
    Charge les règles de catégorisation depuis un fichier YAML.

    Args:
        yaml_path (Path): chemin vers le fichier YAML des règles.

    Returns:
        list[CategoryRule]: liste de dictionnaires contenant les règles,
        par exemple [{'rule': 'chien - chat = dog'}, {'rule': 'default = misc'}].
        Retourne une liste vide en cas d'erreur ou si le fichier est invalide.
    """
    try:
        with open(yaml_path, encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
            rules: list[CategoryRule] = data.get("rules", [])
            if not isinstance(rules, list):
                return []
            return rules
    except (OSError, yaml.YAMLError) as e:
        raise CutMindError(
            "❌ Erreur chargement YAML categs.",
            code=ErrCode.FILE_ERROR,
            ctx=get_step_ctx({"yaml_path": str(yaml_path)}),
        ) from e
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors du chargment du fichier categ.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"yaml_path": str(yaml_path)}),
        ) from exc
