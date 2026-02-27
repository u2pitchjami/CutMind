from enum import Enum
from typing import TypedDict


class AIResult(TypedDict, total=False):
    description: str | None
    keywords: list[str] | None
    quality_rating: float | None
    interest_rating: float | None


class AIOutputType(str, Enum):
    SCENE_ANALYSIS = "scene_analysis"
    SCENE_RATING = "scene_rating"
