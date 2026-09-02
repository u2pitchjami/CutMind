from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SceneAnalysis:
    """
    Résultat d'une analyse PySceneDetect complète conservée en mémoire.

    Les valeurs de content_values sont indexées par numéro de frame.
    Une valeur à None signifie qu'aucune métrique n'est disponible
    pour cette frame.
    """

    fps: float
    duration: float
    content_values: tuple[float | None, ...]

    @property
    def frame_count(self) -> int:
        """Retourne le nombre de frames représentées dans l'analyse."""
        return len(self.content_values)

    def frame_to_seconds(self, frame_number: int) -> float:
        """Convertit un numéro de frame en timestamp en secondes."""
        if frame_number < 0:
            raise ValueError("frame_number doit être >= 0")

        if self.fps <= 0.0:
            raise ValueError("fps doit être > 0")

        return frame_number / self.fps

    def seconds_to_frame(self, timestamp: float) -> int:
        """Convertit un timestamp en secondes vers un numéro de frame."""
        if timestamp < 0.0:
            raise ValueError("timestamp doit être >= 0")

        if self.fps <= 0.0:
            raise ValueError("fps doit être > 0")

        return round(timestamp * self.fps)
