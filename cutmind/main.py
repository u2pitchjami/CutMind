"""
main projet cutmind
"""

from __future__ import annotations

import argparse

from shared.models.config_manager import ConfigManager, set_config
from shared.utils.logger import get_logger
from shared.utils.settings import init_settings


def main(priority: str = "smartcut") -> None:
    """
    main du projet cutmind
    Args:
        priority (str, optional): _description_. Defaults to "smartcut".
    """
    logger = get_logger("CutMind")
    config = ConfigManager(logger=logger)
    set_config(config)
    init_settings(config)

    from shared.video_orchestrator import orchestrate

    orchestrate(priority=priority, logger=logger)


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
    main(priority=args.priority)
