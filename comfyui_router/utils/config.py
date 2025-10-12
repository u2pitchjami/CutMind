"""2025-08-20 - module config en lien avec env."""

# config.py
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Chargement du .env
load_dotenv("/app/config/.env")


class ConfigError(Exception):
    """
    Erreur de configuration (.env / variables d'environnement).
    """


# --- Fonctions utilitaires ---


def get_required(key: str) -> str:
    """
    Récupère la valeur d'une variable env requise.

    Lève ConfigError si absente.
    """
    value = os.getenv(key)
    if value is None:
        raise ConfigError(f"[CONFIG ERROR] La variable {key} est requise mais absente.")
    return value


def get_bool(key: str, default: str = "false") -> bool:
    """
    Retourne la variable env convertie en booléen.
    """
    return os.getenv(key, default).lower() in ("true", "1", "yes", "y")


def get_str(key: str, default: str = "") -> str:
    """
    Retourne la variable env sous forme de chaîne.
    """
    return os.getenv(key, default)


def get_int(key: str, default: int = 0) -> int:
    """
    Retourne la variable env convertie en entier.

    Lève ConfigError si conversion impossible.
    """
    raw = os.getenv(key, str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"[CONFIG ERROR] La variable {key} doit être un entier (valeur: {raw!r}).") from exc


def get_float(key: str, default: float = 0.0) -> float:
    """
    Retourne la variable env convertie en float.

    Lève ConfigError si conversion impossible.
    """
    raw = os.getenv(key, str(default))
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"[CONFIG ERROR] La variable {key} doit être un float (valeur: {raw!r}).") from exc


def get_path_required(key: str) -> str:
    """
    Retourne un chemin (str) *existant* lu depuis l'env.

    Lève ConfigError si absent ou inexistant.
    """

    value = get_required(key).strip()
    abs_path = str(value)
    if not Path(abs_path).exists():
        raise ConfigError(f"[CONFIG ERROR] {key} pointe vers un chemin inexistant: {abs_path}")
    return abs_path


# --- Variables d'environnement accessibles globalement ---

INPUT_DIR: Path = Path(get_path_required("INPUT_DIR"))
OUTPUT_DIR: Path = Path(get_path_required("OUTPUT_DIR"))
WORKFLOW_DIR: Path = Path(get_path_required("WORKFLOW_DIR"))
TRASH_DIR: Path = Path(get_str("TRASH_DIR", ".trash"))
OK_DIR: Path = Path(get_str("OK_DIR", "truc"))
COMFY_URL: str = get_required("COMFY_URL")

WORKFLOW_MAP: dict[str, Path] = {
    "1080p": WORKFLOW_DIR / "Video-Upscaler-Next-Diffusion 1080p.json",
    "720p": WORKFLOW_DIR / "Video-Upscaler-Next-Diffusion 720p.json",
    "Autres": WORKFLOW_DIR / "Video-Upscaler-Next-Diffusion Autres.json",
}

# LOGS
LOG_FILE_PATH = get_str("LOG_FILE_PATH", "logs")
LOG_ROTATION_DAYS = get_int("LOG_ROTATION_DAYS", 100)
LOG_LEVEL: str = get_str("LOG_LEVEL", "INFO").upper()

OK_DIR.mkdir(parents=True, exist_ok=True)
TRASH_DIR.mkdir(parents=True, exist_ok=True)
Path(LOG_FILE_PATH).mkdir(parents=True, exist_ok=True)
