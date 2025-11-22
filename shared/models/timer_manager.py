from datetime import timedelta
import time

from shared.utils.logger import LoggerProtocol


class Timer:
    def __init__(self, label: str, logger: LoggerProtocol):
        self.label = label
        self.logger = logger

    def __enter__(self) -> "Timer":
        self.start = time.perf_counter()
        self.logger.info(f"\u23f3 Début {self.label}...")
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        elapsed = time.perf_counter() - self.start
        self.logger.info(f"✅ {self.label} terminé en {self._format_duration(elapsed)}.")

    @staticmethod
    def _format_duration(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.2f} sec"
        elif seconds < 3600:
            mins, secs = divmod(seconds, 60)
            return f"{int(mins)} min {secs:.1f} sec"
        else:
            td = timedelta(seconds=int(seconds))
            return str(td)
