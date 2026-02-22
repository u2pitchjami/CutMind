from __future__ import annotations

import os
from pathlib import Path
import re
import shutil

from shared.models.db_models import Video
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.config import CUTMIND_BASEDIR
from shared.utils.fs import safe_file_check
from shared.utils.logger import LoggerProtocol, ensure_logger


def sanitize(name: str) -> str:
    try:
        sanitized = re.sub(r'[<>:"/\\|?*]', " ", name)
        return sanitized
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors du sanitize.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"name": name}),
        ) from exc


class FileMover:
    """
    Gère uniquement le déplacement des fichiers validés (sans mise à jour DB).
    """

    def __init__(self) -> None:
        pass

    def move_video_files(
        self,
        video: Video,
        planned_targets: dict[str, Path],
        logger: LoggerProtocol | None = None,
    ) -> bool:
        """
        Déplace de manière atomique les fichiers segments planifiés pour une vidéo.

        Seuls les segments présents dans planned_targets sont traités.
        """
        logger = ensure_logger(logger, __name__)
        logger.debug("🔍 Déplacement des fichiers pour la vidéo : %s", video.name)
        logger.debug(f"planned_targets : {planned_targets}")

        safe_name = sanitize(video.name)
        logger.debug("🔍 Nom sécurisé pour la vidéo : %s", safe_name)

        prepared: list[tuple[Path, Path, Path]] = []

        # Index segments par uid pour accès O(1)
        segments_by_uid = {seg.uid: seg for seg in video.segments}
        logger.debug(f"segments_by_uid : {segments_by_uid}")

        try:
            # ------------------------------------------------------------------
            # Phase PREPARE
            # ------------------------------------------------------------------
            for seg_uid, dst_rel in planned_targets.items():
                seg = segments_by_uid.get(seg_uid)
                if seg is None:
                    raise CutMindError(
                        f"Segment inconnu dans planned_targets : {seg_uid}",
                        code=ErrCode.UNEXPECTED,
                        ctx=get_step_ctx({"video.name": video.name}),
                    )

                logger.debug(
                    "🔍 Segment %s → Destination planifiée : %s",
                    seg.uid,
                    dst_rel,
                )

                if not seg.output_path:
                    raise CutMindError(
                        f"Segment sans chemin source : {seg.uid}",
                        code=ErrCode.UNEXPECTED,
                        ctx=get_step_ctx({"segment.uid": seg.uid}),
                    )

                src_abs = Path(seg.output_path)
                logger.debug("🔍 Segment %s → Source absolue : %s", seg.uid, src_abs)

                dst_final = CUTMIND_BASEDIR / safe_name / Path(dst_rel).name
                dst_temp = dst_final.with_suffix(dst_final.suffix + ".__moving__")

                logger.debug(
                    "🔍 Segment %s → Destination finale : %s (temp=%s)",
                    seg.uid,
                    dst_final,
                    dst_temp,
                )

                # Vérification source (anti-corruption / anti-FUSE)
                safe_file_check(src_abs, logger)

                dst_final.parent.mkdir(parents=True, exist_ok=True)

                logger.debug("⏳ Copie %s -> %s", src_abs, dst_temp)
                shutil.copy2(src_abs, dst_temp)

                # fsync pour garantir l’écriture disque
                with open(dst_temp, "rb") as tmpf:
                    os.fsync(tmpf.fileno())

                prepared.append((src_abs, dst_temp, dst_final))

            # ------------------------------------------------------------------
            # Phase COMMIT (atomique)
            # ------------------------------------------------------------------
            for src_abs, dst_temp, dst_final in prepared:
                os.replace(dst_temp, dst_final)
                if src_abs.exists():
                    os.remove(src_abs)

            logger.info(
                "✅ Déplacement réussi : %s (%d fichiers)",
                video.name,
                len(prepared),
            )
            return True

        except CutMindError as err:
            self._cleanup(prepared)
            raise err.with_context(get_step_ctx({"video.name": video.name})) from err

        except Exception as exc:
            self._cleanup(prepared)
            raise CutMindError(
                "❌ Échec déplacement vidéo.",
                code=ErrCode.UNEXPECTED,
                ctx=get_step_ctx({"video.name": video.name}),
            ) from exc

    @staticmethod
    def safe_copy(src: Path, dst: Path) -> None:
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        except Exception as err:
            raise CutMindError(
                "❌ Échec déplacement vidéo.",
                code=ErrCode.UNEXPECTED,
                ctx=get_step_ctx({"src": src, "dst": dst}),
            ) from err

    @staticmethod
    def _cleanup(prepared: list[tuple[Path, Path, Path]]) -> None:
        for _, dst_temp, _ in prepared:
            try:
                if dst_temp.exists():
                    dst_temp.unlink()
            except Exception as err:
                raise CutMindError(
                    "❌ Échec nettoyage après échec déplacement.",
                    code=ErrCode.UNEXPECTED,
                    ctx=get_step_ctx({"dst_temp": dst_temp}),
                ) from err

    @staticmethod
    def safe_replace(src: Path, dst: Path, logger: LoggerProtocol | None = None) -> None:
        """
        Remplace un fichier même entre FS différents.

        Copie → fsync → rename atomique.
        """
        logger = ensure_logger(logger, __name__)
        import uuid

        move_id = uuid.uuid4().hex[:8]
        logger.debug(
            "MOVE[%s] start | src=%s | dst=%s",
            move_id,
            src,
            dst,
        )
        logger.debug("⏳ Déplacement sécurisé %s -> %s", src, dst)
        # Vérification safe du fichier source

        safe_file_check(src, logger=logger)

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = dst.with_suffix(dst.suffix + ".__moving__")

            # Copie sécurisée dans le temporaire
            FileMover.safe_copy(src, tmp_path)

            # Remplacement atomique
            os.replace(tmp_path, dst)

            # Suppression du fichier source
            if src.exists():
                os.remove(src)
            logger.debug("MOVE[%s] done", move_id)
        except Exception:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception as err:
                raise CutMindError(
                    "❌ Échec cleanup.",
                    code=ErrCode.UNEXPECTED,
                    ctx=get_step_ctx({"tmp_path": tmp_path}),
                ) from err
