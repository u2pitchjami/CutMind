"""
config_manager.py — Gestionnaire YAML avec validation intégrée.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from shared.utils.logger import get_logger

logger = get_logger(__name__)

YamlDict = dict[str, Any]


class ConfigManager:
    """
    Charge, valide et centralise toutes les configurations SmartCut.
    """

    def __init__(self, config_dir: Path | None = None) -> None:
        self.config_dir: Path = config_dir or Path("/app/config")
        self._reload_all()

    # --- Chargement YAML générique --- #
    def _load_yaml(self, filename: str) -> YamlDict:
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
    def _reload_all(self) -> None:
        self.smartcut: YamlDict = self._load_yaml("smartcut.yaml")
        self.comfyui_router: YamlDict = self._load_yaml("comfyui_router.yaml")
        # self.paths: YamlDict = self._load_yaml("paths.yaml")
        # self.keywords: YamlDict = self._load_yaml("keywords.yaml")
        self._ensure_defaults()

    def _ensure_defaults(self) -> None:
        for section in ("smartcut", "comfyui_router", "paths", "keywords"):
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

    def validate(self, strict: bool = True) -> bool:
        """
        Valide la structure minimale des fichiers YAML.
        """
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

    def reload(self) -> None:
        logger.info("♻️ Rechargement complet des fichiers YAML…")
        self._reload_all()
        logger.info("✅ Rechargement terminé.")


# --- Instance globale --- #
CONFIG = ConfigManager()
