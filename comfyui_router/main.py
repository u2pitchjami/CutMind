import argparse

from comfyui_router.models.processor import VideoProcessor
from comfyui_router.utils.config import INPUT_DIR
from comfyui_router.utils.logger import get_logger
from comfyui_router.utils.safe_runner import safe_main

logger = get_logger("Comfyui Router")


@safe_main
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--deinterlace", action="store_true", help="Forcer le désentrelacement des vidéos")
    args = parser.parse_args()

    processor = VideoProcessor()
    for i, video in enumerate(sorted(INPUT_DIR.glob("*.mp4"))):
        if args.limit and i >= args.limit:
            break
        processor.process(video_path=video, force_deinterlace=args.deinterlace)


if __name__ == "__main__":
    main()
