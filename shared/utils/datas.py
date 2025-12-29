"""
conversion de data pour insertion en base
"""

from __future__ import annotations

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx


def format_resolution(res: tuple[int, int] | None) -> str | None:
    """
    Convertit une résolution (tuple) en chaîne 'WxH'.
    Retourne None si invalide ou vide.
    """
    try:
        if not res or not all(isinstance(x, int) and x > 0 for x in res):
            return None
        return f"{res[0]}x{res[1]}"
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors de format_resolution.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"res": res}),
        ) from exc


def resolution_str_to_tuple(res: str) -> tuple[int, int]:
    try:
        w, h = res.lower().split("x")
        return int(w), int(h)
    except Exception as exc:
        raise CutMindError(
            "❌ Résolution invalide (format attendu 'WxH')",
            code=ErrCode.FILE_ERROR,
            ctx={"resolution": res},
        ) from exc
