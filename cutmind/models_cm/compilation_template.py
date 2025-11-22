from dataclasses import dataclass, field

import yaml


@dataclass
class KeywordRule:
    keyword: str
    ratio: float  # between 0.0 and 1.0

    def validate(self) -> None:
        if not (0.0 <= self.ratio <= 1.0):
            raise ValueError(f"Invalid ratio {self.ratio} for keyword {self.keyword}")


@dataclass
class CompilationBlock:
    category: str
    duration: int | None = None
    count: int | None = None
    keyword_rules: list[KeywordRule] = field(default_factory=list)
    keywords_exclude: list[str] = field(default_factory=list)
    recent_days: int | None = None
    recent_ratio: float = 0.0  # 0 to 1

    def validate(self) -> None:
        if (self.duration is None and self.count is None) or (self.duration and self.count):
            raise ValueError(f"Block in category '{self.category}' must define either 'duration' or 'count', not both.")
        if not (0.0 <= self.recent_ratio <= 1.0):
            raise ValueError(f"Invalid recent_ratio {self.recent_ratio} in category '{self.category}'")
        for rule in self.keyword_rules:
            rule.validate()


@dataclass
class CompilationTemplate:
    title: str
    output_filename: str
    sequence: list[CompilationBlock]
    repeat: int = 1

    def validate(self) -> None:
        if not self.sequence:
            raise ValueError("Template must include at least one block.")
        if self.repeat < 1:
            raise ValueError("Repeat must be >= 1.")
        for block in self.sequence:
            block.validate()


def load_template(path: str) -> CompilationTemplate:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    sequence = []
    for block in raw["sequence"]:
        keyword_rules = [KeywordRule(**rule) for rule in block.get("keyword_rules", [])]
        sequence.append(
            CompilationBlock(
                category=block["category"],
                duration=block.get("duration"),
                count=block.get("count"),
                keyword_rules=keyword_rules,
                keywords_exclude=block.get("keywords_exclude", []),
                recent_days=block.get("recent_days"),
                recent_ratio=block.get("recent_ratio", 0.0),
            )
        )

    template = CompilationTemplate(
        title=raw["title"],
        output_filename=raw["output_filename"],
        repeat=raw.get("repeat", 1),
        sequence=sequence,
    )
    template.validate()
    return template
