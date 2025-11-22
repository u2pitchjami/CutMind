from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

import yaml

from shared.utils.config import CATEGORIES_RULES
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger


class CategoryRule(TypedDict, total=False):
    rule: str


@with_child_logger
def load_category_rules(yaml_path: Path, logger: LoggerProtocol | None = None) -> list[CategoryRule]:
    """
    Charge les règles de catégorisation depuis un fichier YAML.

    Args:
        yaml_path (Path): chemin vers le fichier YAML des règles.

    Returns:
        list[CategoryRule]: liste de dictionnaires contenant les règles,
        par exemple [{'rule': 'chien - chat = dog'}, {'rule': 'default = misc'}].
        Retourne une liste vide en cas d'erreur ou si le fichier est invalide.
    """
    logger = ensure_logger(logger, __name__)
    try:
        with open(yaml_path, encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
            rules: list[CategoryRule] = data.get("rules", [])
            if not isinstance(rules, list):
                logger.warning("⚠️ Format YAML inattendu : 'rules' n'est pas une liste dans %s", yaml_path)
                return []
            return rules
    except (OSError, yaml.YAMLError) as e:
        logger.error("❌ Erreur chargement YAML (%s): %s", yaml_path, e)
        return []


@with_child_logger
def match_category(
    keywords: list[str], rules_yaml: Path = CATEGORIES_RULES, logger: LoggerProtocol | None = None
) -> str | None:
    """
    Détermine la catégorie d’un segment selon des règles déclaratives YAML.

    Args:
        keywords (List[str]): liste des mots-clés du segment
        rules_yaml (Path): chemin du fichier YAML des règles

    Returns:
        str | None: catégorie trouvée ou None
    """
    logger = ensure_logger(logger, __name__)
    keywords = [kw.lower().strip() for kw in keywords]
    rules = load_category_rules(rules_yaml, logger=logger)

    for idx, rule_entry in enumerate(rules, start=1):
        rule_str = rule_entry.get("rule", "").strip()
        if not rule_str:
            continue

        # Parsing de la règle : inclusions, exclusions, résultat
        if "=" not in rule_str:
            logger.warning("⚠️ Règle #%d invalide (pas de '=') : %s", idx, rule_str)
            continue

        condition_part, result = [s.strip() for s in rule_str.split("=", 1)]
        if not result:
            return None
        result = result

        # Gestion du cas "default"
        if condition_part.lower() == "default":
            logger.debug("🏷️ Règle #%d par défaut → %s", idx, result)
            return result

        # Analyse des inclusions et exclusions
        includes = []
        excludes = []
        for token in condition_part.split():
            if "-" in token:
                inc, exc = [t.strip() for t in token.split("-", 1)]
                includes.append(inc)
                excludes.append(exc)
            else:
                includes.append(token)

        # Évaluation de la règle
        if all(kw in keywords for kw in includes) and not any(kw in keywords for kw in excludes):
            logger.debug("✅ Règle #%d appliquée: %s → %s", idx, rule_str, result)
            return result

    logger.debug("❌ Aucune règle ne correspond pour %s", keywords)
    return None
