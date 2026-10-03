from dataclasses import dataclass
from pathlib import Path

from shared.models.db_models import Segment


@dataclass(slots=True, frozen=True)
class Compilation:
    title: str
    filename: str
    output_path: Path
    manifest_path: Path | None
    template_name: str | None
    segments: list[Segment]
