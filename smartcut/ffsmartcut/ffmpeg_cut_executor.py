from __future__ import annotations

import ffmpeg  # type: ignore


class FfmpegCutExecutor:
    """
    Exécuteur technique pur : coupe une vidéo sans aucune logique
    métier ou orchestration.
    """

    def cut(self, input_path: str, start: float, end: float, output_path: str) -> None:
        try:
            (
                ffmpeg.input(input_path, ss=start, to=end)
                .output(output_path, codec="copy", loglevel="error")
                .overwrite_output()
                .run(quiet=True)
            )
        except Exception as exc:
            raise RuntimeError(f"ffmpeg failed to cut video ({input_path}) [{start}→{end}]") from exc
