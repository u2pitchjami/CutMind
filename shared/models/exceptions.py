# /exceptions.py
from __future__ import annotations

from enum import Enum
import inspect
from typing import Any


class ErrCode(str, Enum):
    FFMPEG = "FFMPEG"
    BADFORMAT = "BADFORMAT"
    FILE_ERROR = "FILE_ERROR"
    CONTEXT = "CONTEXT"
    MODEL = "MODEL"
    VIDEO = "VIDEO"
    UNEXPECTED = "UNEXPECTED"
    NOFILE = "NOFILE"
    IAERROR = "IAERROR"
    DB = "DB"
    NOT_FOUND = "NOT_FOUND"
    TIMEOUT = "TIMEOUT"
    NETWORK = "NETWORK"


class CutMindError(RuntimeError):
    """
    Erreur métier avec code + contexte structuré.
    """

    __slots__ = ("code", "ctx")

    def __init__(
        self,
        message: str,
        *,
        code: ErrCode,
        ctx: dict[str, Any] | None = None,
        original_exception: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.ctx = ctx or {}
        self.original_exception = original_exception

    def with_context(self, extra: dict[str, Any]) -> CutMindError:
        # N’écrase pas ce qui existe déjà
        for k, v in extra.items():
            self.ctx.setdefault(k, v)
        return self

    def __str__(self) -> str:
        base = f"{self.code}: {super().__str__()} | ctx: {self.ctx}"
        if self.original_exception:
            base += f" | caused by: {self.original_exception!r}"
        return base


def get_step_ctx(extra: dict[str, Any] | None = None, depth: int = 1) -> dict[str, Any]:
    """
    Génère un contexte enrichi avec le nom de la fonction appelante ('step').

    :param extra: autres clés à fusionner dans le contexte
    :param depth: niveau d'appel dans la stack (1 par défaut)
    :return: dict compatible pour ctx=...
    """
    func_name = inspect.stack()[depth][3]
    base = {"step": func_name}
    if extra:
        base.update(extra)
    return base
