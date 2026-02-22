from dataclasses import dataclass


@dataclass
class SegmentFrameHash:
    segment_id: int
    frame_index: int
    hash_type: str  # "phash"
    hash_value: bytes

    def to_sql_values(self) -> tuple[int, int, str, bytes]:
        return (
            self.segment_id,
            self.frame_index,
            self.hash_type,
            self.hash_value,
        )
