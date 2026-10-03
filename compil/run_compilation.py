import argparse
from datetime import datetime
from pathlib import Path

from compil.compil_db_model import Compilation
from compil.compilation_builder import make_compilation
from compil.compilation_template import load_template
from compil.segment_selector import select_segments_for_block
from db.repository import CutMindRepository
from shared.utils.config import EXPORTS_COMPIL
from shared.utils.logger import get_logger
from shared.utils.settings import get_settings

logger = get_logger("CutMind Compil")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--template",
        required=True,
        help="Chemin du fichier YAML de template",
    )
    args = parser.parse_args()
    from shared.models.config_manager import bootstrap_process

    bootstrap_process(logger=logger)
    settings = get_settings()
    template_path = Path(args.template)
    template = load_template(str(template_path))
    timestamp = datetime.now().strftime("%y%m%d%H%M%S")

    repo = CutMindRepository()
    all_segments = []
    used_uids: set[str] = set()

    for i in range(template.repeat):
        logger.info(
            "🔁 Boucle %d / %d",
            i + 1,
            template.repeat,
        )

        for block in template.sequence:
            block_segments = select_segments_for_block(
                block=block,
                repo=repo,
                used_uids=used_uids,
                max_overflow_ratio=template.max_overflow_ratio,
                logger=logger,
            )

            all_segments.extend(block_segments)

    output_path = Path(EXPORTS_COMPIL) / f"{timestamp}_{template.output_filename}"
    manifest_path = output_path.with_suffix(".json")

    make_compilation(
        segments=all_segments,
        output_path=output_path,
        manifest_path=manifest_path,
        logger=logger,
    )

    compilation = Compilation(
        title=template.title,
        filename=output_path.name,
        output_path=output_path,
        manifest_path=manifest_path,
        template_name=template_path.name,
        segments=all_segments,
    )

    compilation_id = repo.insert_compilation_with_segments(compilation)

    logger.info(
        "💾 Compilation enregistrée en BDD : id=%d",
        compilation_id,
    )
