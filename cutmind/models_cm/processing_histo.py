from dataclasses import dataclass
from datetime import datetime


@dataclass
class ProcessingHistory:
    video_id: int
    segment_id: int | None
    video_name: str
    segment_uid: str | None
    action: str  # ex: 'analyse_ia', 'comfyui_router', etc.
    status: str  # 'ok', 'partial', 'error', 'skipped'
    message: str
    started_at: datetime
    ended_at: datetime
    id: int | None = None

    @property
    def duration_ms(self) -> int:
        delta = self.ended_at - self.started_at
        return int(delta.total_seconds() * 1000)

    def to_sql_values(self) -> tuple[int, int | None, str, str | None, str, str, str, str, str]:
        return (
            self.video_id,
            self.segment_id,
            self.video_name,
            self.segment_uid,
            self.action,
            self.status,
            self.message,
            self.started_at.strftime("%Y-%m-%d %H:%M:%S"),
            self.ended_at.strftime("%Y-%m-%d %H:%M:%S"),
        )
