from typing import Literal, TypedDict


class AIResult(TypedDict):
    description: str | None
    keywords: list[str] | None


AIOutputType = Literal["full", "keywords", "description"]
