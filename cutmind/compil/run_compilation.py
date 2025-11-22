import argparse
from pathlib import Path

from cutmind.compil.compilation_builder import make_compilation
from cutmind.compil.segment_selector import select_segments_for_block
from cutmind.db.repository import CutMindRepository
from cutmind.models_cm.compilation_template import load_template
from shared.utils.config import EXPORTS_COMPIL
from shared.utils.logger import get_logger

logger = get_logger("CutMind Compil")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", required=True, help="Chemin du fichier YAML de template")
    args = parser.parse_args()

    template_path = Path(args.template)
    template = load_template(str(template_path))

    repo = CutMindRepository()
    all_segments = []

    for i in range(template.repeat):
        logger.info("🔁 Boucle %d / %d", i + 1, template.repeat)
        for block in template.sequence:
            block_segments = select_segments_for_block(block, repo, logger=logger)
            all_segments.extend(block_segments)

    output_path = Path(f"{EXPORTS_COMPIL}/{template.output_filename}")
    manifest_path = output_path.with_suffix(".json")

    make_compilation(
        segments=all_segments, output_path=output_path, manifest_path=manifest_path, compress="cuda", logger=logger
    )
