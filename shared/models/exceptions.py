# exceptions.py
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
    Erreur métier structurée avec code + contexte.
    L'exception d'origine est propagée via `raise ... from exc`.
    """

    __slots__ = ("code", "ctx")

    def __init__(
        self,
        message: str,
        *,
        code: ErrCode,
        ctx: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code: ErrCode = code
        self.ctx: dict[str, Any] = ctx or {}

    def with_context(self, extra: dict[str, Any]) -> CutMindError:
        """Ajoute du contexte sans écraser les clés existantes."""
        for key, value in extra.items():
            self.ctx.setdefault(key, value)
        return self

    def to_dict(self) -> dict[str, Any]:
        """Représentation structurée utile pour logs JSON."""
        return {
            "code": self.code.value,
            "message": str(super()),
            "ctx": self.ctx,
        }

    def __str__(self) -> str:
        return f"{self.code}: {super().__str__()} | ctx: {self.ctx}"


def get_step_ctx(
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    frame = inspect.currentframe()
    func_name = "unknown"

    if frame and frame.f_back:
        func_name = frame.f_back.f_code.co_name

    ctx: dict[str, Any] = {"step": func_name}

    if extra:
        ctx.update(extra)

    return ctx
