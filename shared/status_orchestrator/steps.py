from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class OrchestratorStep:
    name: str
    can_run: Callable[..., bool]
    run: Callable[..., None]
