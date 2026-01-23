"""
main projet cutmind
"""

from __future__ import annotations

import argparse

from shared.utils.logger import get_logger


def main() -> None:
    """
    main du projet cutmind
    Args:
        priority (str, optional): _description_. Defaults to "smartcut".
    """
    logger = get_logger("CutMind_Orchestrator")
    from shared.models.config_manager import bootstrap_process

    bootstrap_process(logger=logger)

    from cutmind.orchestrators.master import run_master

    run_master(logger=logger)


# ============================================================
# 🚀 CLI
# ============================================================
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Orchestrateur SmartCut + CutMind Router")
    parser.add_argument(
        "--priority",
        choices=["smartcut", "router"],
        default="smartcut",
        help="Source prioritaire (défaut: smartcut)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    main()
