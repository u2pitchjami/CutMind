from __future__ import annotations

from pathlib import Path

from cutmind.executors.categ.load_categ_yaml import load_category_rules
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.config import CATEGORIES_RULES
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger


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

    try:
        rules = load_category_rules(rules_yaml)

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
    except CutMindError as err:
        raise err.with_context(get_step_ctx({"keywords": keywords})) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors de l'attribution des categs.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"keywords": keywords}),
        ) from exc
