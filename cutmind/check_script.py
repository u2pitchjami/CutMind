"""
main projet cutmind
"""

from __future__ import annotations

from cutmind.services.check.already_enhanced import process_standard_videos
from cutmind.services.check.check_categ_missing import check_segments_missing_category
from cutmind.services.check.check_files import check_enhanced_segments
from cutmind.services.check.check_status import check_all_video_segment_status_rules
from shared.models.config_manager import ConfigManager, set_config
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.logger import get_logger
from shared.utils.settings import init_settings


def main_check_script() -> None:
    """
        main check_script
    .
    """
    logger = get_logger("CutMind_Check")
    try:
        check_segments_missing_category(expected_statuses=["validated", "enhanced"], logger=logger)
        check_all_video_segment_status_rules(logger=logger)
        check_enhanced_segments(max_videos=50, logger=logger)
        process_standard_videos(limit=50, logger=logger)
    except CutMindError as err:
        raise err.with_context(get_step_ctx()) from err
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur lors du script Check.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx(),
        ) from exc


# ============================================================
# 🚀 CLI
# ============================================================


if __name__ == "__main__":
    logger = get_logger("CutMind_Check")
    config = ConfigManager(logger=logger)
    set_config(config)
    init_settings(config)
    main_check_script()
