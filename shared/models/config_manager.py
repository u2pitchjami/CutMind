"""
config_manager.py — Gestionnaire YAML avec validation intégrée.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger
from shared.utils.settings import init_settings

YamlDict = dict[str, Any]


class ConfigManager:
    """
    Charge, valide et centralise toutes les configurations SmartCut.
    """

    @with_child_logger
    def __init__(self, config_dir: Path | None = None, logger: LoggerProtocol | None = None) -> None:
        logger = ensure_logger(logger, __name__)
        self.config_dir: Path = config_dir or Path("/app/config")
        self._reload_all(logger=logger)

    # --- Chargement YAML générique --- #
    @with_child_logger
    def _load_yaml(self, filename: str, logger: LoggerProtocol | None = None) -> YamlDict:
        logger = ensure_logger(logger, __name__)
        path = self.config_dir / filename
        if not path.exists():
            logger.warning("⚠️ Fichier de configuration manquant : %s", path)
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                data: Any = yaml.safe_load(f)
                if not isinstance(data, dict):
                    logger.warning("⚠️ %s n'est pas un dictionnaire YAML valide.", filename)
                    return {}
                logger.debug("✅ %s chargé (%d clés)", filename, len(data))
                return data
        except yaml.YAMLError as e:
            logger.error("Erreur de parsing YAML pour %s: %s", filename, e)
            return {}
        except Exception as exc:
            logger.error("💥 Erreur inattendue lors du chargement de %s: %s", filename, exc)
            return {}

    # --- Chargement complet --- #
    @with_child_logger
    def _reload_all(self, logger: LoggerProtocol | None = None) -> None:
        logger = ensure_logger(logger, __name__)
        self.smartcut: YamlDict = self._load_yaml("smartcut.yaml", logger=logger)
        self.comfyui_router: YamlDict = self._load_yaml("comfyui_router.yaml", logger=logger)
        # self.paths: YamlDict = self._load_yaml("paths.yaml")
        # self.keywords: YamlDict = self._load_yaml("keywords.yaml")
        self._ensure_defaults(logger=logger)

    @with_child_logger
    def _ensure_defaults(self, logger: LoggerProtocol | None = None) -> None:
        logger = ensure_logger(logger, __name__)
        for section in ("smartcut", "comfyui_router", "cutmindpaths", "keywords"):
            if not hasattr(self, section):
                setattr(self, section, {})
        logger.debug("✅ Vérification des sections terminée (fallbacks OK).")

    # --- Accès simplifié --- #
    def get(self, section: str, key: str, default: Any = None) -> Any:
        section_data = getattr(self, section, {})
        if isinstance(section_data, dict):
            return section_data.get(key, default)
        return default

    # --- Validation récursive --- #
    def _validate_section(
        self, data: dict[str, Any], required_structure: dict[str, Any] | list[str], path: str = ""
    ) -> list[str]:
        errors = []
        if isinstance(required_structure, dict):
            for key, sub_required in required_structure.items():
                if key not in data:
                    errors.append(f"⛔ Clé manquante : {path + key}")
                    continue
                sub_data = data.get(key, {})
                errors += self._validate_section(sub_data, sub_required, path + f"{key}.")
        elif isinstance(required_structure, list):
            for key in required_structure:
                if key not in data:
                    errors.append(f"⛔ Clé manquante : {path + key}")
        return errors

    @with_child_logger
    def validate(self, strict: bool = True, logger: LoggerProtocol | None = None) -> bool:
        """
        Valide la structure minimale des fichiers YAML.
        """
        logger = ensure_logger(logger, __name__)
        logger.info("🧩 Validation de la configuration SmartCut…")

        errors: list[str] = []

        required = {
            "smartcut": {
                "generate_keywords": [
                    "model_4b",
                    "model_8b",
                    "free_vram_8b",
                    "free_vram_4b",
                    "load_in_4bit",
                    "bnb_4bit_quant_type",
                    "bnb_4bit_compute_dtype",
                ]
            }
        }

        for section, required_keys in required.items():
            data = getattr(self, section, {})
            errors += self._validate_section(data, required_keys, path=f"{section}.")

        if errors:
            for err in errors:
                logger.error(err)
            if strict:
                raise ValueError(f"Configuration invalide ({len(errors)} erreurs).")
            else:
                logger.warning("⚠️ Validation partielle — %d clés manquantes.", len(errors))
                return False

        logger.info("✅ Validation réussie — toutes les clés requises sont présentes.")
        return True

    @with_child_logger
    def reload(self, logger: LoggerProtocol | None = None) -> None:
        logger = ensure_logger(logger, __name__)
        logger.info("♻️ Rechargement complet des fichiers YAML…")
        self._reload_all(logger=logger)
        logger.info("✅ Rechargement terminé.")


# --- Instance globale --- #
_CONFIG: ConfigManager | None = None


def get_config() -> ConfigManager:
    if _CONFIG is None:
        raise RuntimeError("CONFIG non initialisé. Appeler boot() ou main() d'abord.")
    return _CONFIG


def set_config(cfg: ConfigManager) -> None:
    global _CONFIG
    _CONFIG = cfg


@with_child_logger
def reload_and_apply(logger: LoggerProtocol | None = None) -> None:
    """
    Recharge les YAML et met à jour SETTINGS d’un seul coup.

    Fonction utilitaire destinée aux modules haut-niveau.
    """
    logger = ensure_logger(logger, __name__)
    cfg = get_config()
    cfg.reload(logger=logger)
    init_settings(cfg)


def bootstrap_process(logger: LoggerProtocol | None = None) -> None:
    config = ConfigManager(logger=logger)
    set_config(config)
    init_settings(config)
