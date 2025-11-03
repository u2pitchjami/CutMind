""" """

from __future__ import annotations

import argparse
from itertools import chain

from comfyui_router.models_cr.processor import VideoProcessor
from shared.utils.config import INPUT_DIR, OUTPUT_DIR, SAFE_FORMATS
from shared.utils.logger import get_logger
from shared.utils.safe_runner import safe_main
from shared.utils.trash import delete_files

logger = get_logger("Comfyui Router")


@safe_main
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--deinterlace", action="store_true", help="Forcer le désentrelacement des vidéos")
    args = parser.parse_args()
    delete_files(path=OUTPUT_DIR, ext="*.png")
    delete_files(path=OUTPUT_DIR, ext="*.mp4")
    processor = VideoProcessor()
    videos = sorted(chain.from_iterable(INPUT_DIR.glob(f"*{ext}") for ext in SAFE_FORMATS))
    for i, video in enumerate(videos):
        if args.limit and i >= args.limit:
            break
        processor.process(video_path=video, force_deinterlace=args.deinterlace)


if __name__ == "__main__":
    main()
