""" """

from __future__ import annotations

import torch

from shared.utils.logger import get_logger

logger = get_logger(__name__)


def get_free_vram_gb() -> float:
    """
    Retourne la VRAM libre en Go.
    """
    if not torch.cuda.is_available():
        return 0.0
    free, _ = torch.cuda.mem_get_info()
    vram: float = free / 1024**3
    return vram
