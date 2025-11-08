"""
Gestion centralisée des chemins SmartCut / CutMind
==================================================

Convertit les chemins relatifs ou logiques des JSON SmartCut en chemins absolus réels,
et inversement, pour assurer la compatibilité entre environnements et outils.

Exemples :
  - /basedir/...   →  /mnt/user/Zin-progress/comfyui-nvidia/basedir/...
  - /CutMind/...   →  /mnt/user/Projets/CutMind/...
"""

from __future__ import annotations

from pathlib import Path

# --------------------------------------------------------------------
# 📁 Dossiers racine absolus (adaptés à ton environnement)
# --------------------------------------------------------------------
SMARTCUT_BASEDIR = Path("/mnt/user/Zin-progress/comfyui-nvidia/basedir")
CUTMIND_BASEDIR = Path("/mnt/user/Zin-progress/CutMind")

# --------------------------------------------------------------------
# 🧩 Préfixes "logiques" utilisés dans les JSON
# --------------------------------------------------------------------
SMARTCUT_PREFIX = Path("/basedir")
CUTMIND_PREFIX = Path("/CutMind")


def resolve_path(path: str | Path) -> Path:
    """
    Convertit un chemin logique ou relatif en chemin absolu réel.

    - /basedir/... → SMARTCUT_BASEDIR
    - /CutMind/... → CUTMIND_BASEDIR
    - relatif → SMARTCUT_BASEDIR / ...
    - absolu → renvoyé tel quel
    """
    if not path:
        return Path()

    p = Path(path)

    # ✅ Cas 1 : déjà absolu réel (non logique)
    if p.is_absolute() and not str(p).startswith(("/basedir", "/CutMind")):
        return p

    # ✅ Cas 2 : chemin logique SmartCut
    if str(p).startswith(str(SMARTCUT_PREFIX)):
        rel = p.relative_to(SMARTCUT_PREFIX)
        return SMARTCUT_BASEDIR / rel

    # ✅ Cas 3 : chemin logique CutMind
    if str(p).startswith(str(CUTMIND_PREFIX)):
        rel = p.relative_to(CUTMIND_PREFIX)
        return CUTMIND_BASEDIR / rel

    # ✅ Cas 4 : chemin relatif (on le suppose dans SmartCut)
    return SMARTCUT_BASEDIR / p


def to_logical_path(path: str | Path) -> Path:
    """
    Convertit un chemin absolu réel vers sa forme logique (commençant par /basedir ou /CutMind).
    """
    if not path:
        return Path()

    p = Path(path)

    if str(p).startswith(str(SMARTCUT_BASEDIR)):
        rel = p.relative_to(SMARTCUT_BASEDIR)
        return SMARTCUT_PREFIX / rel

    if str(p).startswith(str(CUTMIND_BASEDIR)):
        rel = p.relative_to(CUTMIND_BASEDIR)
        return CUTMIND_PREFIX / rel

    return p  # non mappable
