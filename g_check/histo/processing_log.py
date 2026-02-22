from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime

from b_db.repository import CutMindRepository
from g_check.histo.processing_histo import ProcessingHistory
from shared.models.db_models import Segment, Video  # adapte si besoin
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx


@contextmanager
def processing_step(video: Video, segment: Segment | None, action: str) -> Generator[ProcessingHistory, None, None]:
    """
    Context manager pour gérer un cycle complet de logging dans processing_history.
    - insert automatique en début de step
    - update automatique en fin avec ended_at
    - capture automatique des exceptions
    """
    if not video.id:
        raise CutMindError(
            "Vidéo introuvable en base de données pour l'ID",
            code=ErrCode.NOT_FOUND,
        )

    repo = CutMindRepository()
    history = ProcessingHistory(
        video_id=video.id,
        segment_id=segment.id if segment else None,
        video_name=video.name,
        segment_uid=segment.uid if segment else None,
        action=action,
        status="pending",
        message="",
        started_at=datetime.utcnow(),
        ended_at=datetime.utcnow(),  # placeholder
    )

    repo.insert_processing_history(history)

    try:
        yield history  # le code du bloc with est exécuté ici
        history.status = history.status or "ok"
        history.message = history.message or "OK"
    except Exception as exc:
        history.status = "error"
        history.message = str(exc)
        raise
    finally:
        history.ended_at = datetime.utcnow()
        try:
            repo.update_processing_history(history)
        except Exception as update_exc:
            raise CutMindError(
                "❌ Erreur lors de la mise à jour de processing_history",
                code=ErrCode.DB,
                ctx=get_step_ctx(
                    {"segment_id" if segment else "video_id": segment.id if segment else video.id, "action": action}
                ),
            ) from update_exc
