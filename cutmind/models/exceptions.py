# brainops/core/exceptions.py
from __future__ import annotations


# class CutmindError(RuntimeError):
#     """
#     Erreur métier avec code + contexte structuré.
#     """

#     __slots__ = ("code", "ctx")

#     def __init__(self, message: str, *, code: ErrCode, ctx: Mapping[str, Any] | None = None) -> None:
#         super().__init__(message)
#         self.code = code
#         self.ctx: dict[str, Any] = dict(ctx or {})

#     def with_context(self, extra: dict[str, Any]) -> CutmindError:
#         # N’écrase pas ce qui existe déjà
#         for k, v in extra.items():
#             self.ctx.setdefault(k, v)
#         return self

#     def __str__(self) -> str:  # utile dans les logs
#         return f"{self.code}: {super().__str__()}"
