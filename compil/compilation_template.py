"""Models and loader for CutMind compilation templates."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_MAX_OVERFLOW_RATIO = 0.25


@dataclass(slots=True, frozen=True)
class KeywordRule:
    """Keyword constraint applied to a compilation block."""

    keyword: str
    ratio: float

    def validate(self) -> None:
        if not self.keyword.strip():
            raise ValueError("Keyword cannot be empty.")

        if not 0.0 <= self.ratio <= 1.0:
            raise ValueError(f"Invalid ratio {self.ratio} for keyword '{self.keyword}'.")


@dataclass(slots=True, frozen=True)
class CompilationBlock:
    """Selection rules for one compilation block."""

    category: str
    duration: int | None = None
    count: int | None = None

    keyword_rules: list[KeywordRule] = field(default_factory=list)
    keywords_exclude: list[str] = field(default_factory=list)

    recent_days: int | None = None
    recent_ratio: float = 0.0

    def validate(self) -> None:
        if not self.category.strip():
            raise ValueError("Compilation block category cannot be empty.")

        if (self.duration is None) == (self.count is None):
            raise ValueError(f"Block '{self.category}' must define exactly one of 'duration' or 'count'.")

        if self.duration is not None and self.duration <= 0:
            raise ValueError(f"Duration must be > 0 for category '{self.category}'.")

        if self.count is not None and self.count <= 0:
            raise ValueError(f"Count must be > 0 for category '{self.category}'.")

        if self.recent_days is not None and self.recent_days <= 0:
            raise ValueError(f"recent_days must be > 0 for category '{self.category}'.")

        if not 0.0 <= self.recent_ratio <= 1.0:
            raise ValueError(f"Invalid recent_ratio {self.recent_ratio} for category '{self.category}'.")

        if self.recent_ratio > 0.0 and self.recent_days is None:
            raise ValueError(f"Block '{self.category}' defines recent_ratio without recent_days.")

        for rule in self.keyword_rules:
            rule.validate()


@dataclass(slots=True, frozen=True)
class CompilationTemplate:
    """Complete CutMind compilation template."""

    title: str
    output_filename: str
    sequence: list[CompilationBlock]
    repeat: int = 1
    max_overflow_ratio: float = DEFAULT_MAX_OVERFLOW_RATIO

    def validate(self) -> None:
        if not self.title.strip():
            raise ValueError("Template title cannot be empty.")

        if not self.output_filename.strip():
            raise ValueError("Template output_filename cannot be empty.")

        if not self.sequence:
            raise ValueError("Template must include at least one block.")

        if self.repeat < 1:
            raise ValueError("Repeat must be >= 1.")

        if not 0.0 <= self.max_overflow_ratio <= 1.0:
            raise ValueError("max_overflow_ratio must be between 0.0 and 1.0.")

        for block in self.sequence:
            block.validate()


def _parse_block(raw_block: dict[str, Any]) -> CompilationBlock:
    keyword_rules = [
        KeywordRule(
            keyword=str(rule["keyword"]),
            ratio=float(rule["ratio"]),
        )
        for rule in raw_block.get("keyword_rules", [])
    ]

    return CompilationBlock(
        category=str(raw_block["category"]),
        duration=raw_block.get("duration"),
        count=raw_block.get("count"),
        keyword_rules=keyword_rules,
        keywords_exclude=[str(keyword) for keyword in raw_block.get("keywords_exclude", [])],
        recent_days=raw_block.get("recent_days"),
        recent_ratio=float(raw_block.get("recent_ratio", 0.0)),
    )


def load_template(path: str | Path) -> CompilationTemplate:
    """Load and validate a compilation template from YAML."""
    template_path = Path(path)

    with template_path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file)

    if not isinstance(raw, dict):
        raise ValueError(f"Invalid compilation template: {template_path}")

    raw_sequence = raw.get("sequence")

    if not isinstance(raw_sequence, list):
        raise ValueError("Template 'sequence' must be a list.")

    sequence = [_parse_block(raw_block) for raw_block in raw_sequence if isinstance(raw_block, dict)]

    template = CompilationTemplate(
        title=str(raw["title"]),
        output_filename=str(raw["output_filename"]),
        repeat=int(raw.get("repeat", 1)),
        max_overflow_ratio=float(
            raw.get(
                "max_overflow_ratio",
                DEFAULT_MAX_OVERFLOW_RATIO,
            )
        ),
        sequence=sequence,
    )

    template.validate()

    return template
