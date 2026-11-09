from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import uuid

from shared.models.db_models import Video
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.config import (
    BATCH_FRAMES_DIR_SC,
    COLOR_BLUE,
    COLOR_CYAN,
    COLOR_GREEN,
    COLOR_PURPLE,
    COLOR_RED,
    COLOR_RESET,
    CUTMIND_BASEDIR,
    OUTPUT_DIR_SC,
    POST_CUT_DIR_SC,
)
from shared.utils.fs import safe_file_check
from shared.utils.logger import LoggerProtocol, ensure_logger, get_logger
from shared.utils.remove_empty_dirs import remove_empty_dirs


def sanitize(name: str) -> str:
    """Nettoie un nom afin qu'il puisse être utilisé comme nom de dossier."""
    try:
        sanitized = re.sub(r'[<>:"/\\|?*]', " ", name)
        return sanitized
    except Exception as exc:
        raise CutMindError(
            "❌ Erreur inattendue lors du sanitize.",
            code=ErrCode.UNEXPECTED,
            ctx=get_step_ctx({"name": name}),
        ) from exc


CLEANABLE_ROOTS: tuple[Path, ...] = (
    BATCH_FRAMES_DIR_SC,
    OUTPUT_DIR_SC,
    POST_CUT_DIR_SC,
    CUTMIND_BASEDIR,
)


class FileMover:
    """
    Gère uniquement le déplacement des fichiers validés.

    Aucune mise à jour DB n'est réalisée ici.
    Les opérations de déplacement sont idempotentes :
    un fichier déjà présent à sa destination est considéré comme traité.
    """

    def __init__(self) -> None:
        self.logger = get_logger("CutMind-Mover")

    def move_video_files(
        self,
        video: Video,
        planned_targets: dict[str, Path],
    ) -> bool:
        """
        Déplace de manière atomique les fichiers segments planifiés pour une vidéo.

        Seuls les segments présents dans planned_targets sont traités.

        Si un fichier est déjà exactement à sa destination, aucune opération
        filesystem n'est effectuée et le segment est considéré comme traité.
        """
        logger = ensure_logger(self.logger, __name__)

        logger.debug(
            "🔍 Déplacement des fichiers pour la vidéo : %s",
            video.name,
        )
        logger.debug("planned_targets : %s", planned_targets)

        safe_name = sanitize(video.name)

        logger.debug(
            "🔍 Nom sécurisé pour la vidéo : %s",
            safe_name,
        )

        prepared: list[tuple[Path, Path, Path]] = []
        already_in_place = 0

        # Index des segments par UID pour accès O(1).
        segments_by_uid = {seg.uid: seg for seg in video.segments}

        logger.debug(
            "segments_by_uid : %s",
            segments_by_uid,
        )

        try:
            # ------------------------------------------------------------------
            # Phase PREPARE
            # ------------------------------------------------------------------
            for seg_uid, dst_rel in planned_targets.items():
                logger.debug(
                    "🔍 Traitement du segment %s → Destination planifiée : %s",
                    seg_uid,
                    dst_rel,
                )

                seg = segments_by_uid.get(seg_uid)

                logger.debug(
                    "segments_by_uid.get(%s) : %s",
                    seg_uid,
                    seg,
                )

                if seg is None:
                    raise CutMindError(
                        f"Segment inconnu dans planned_targets : {seg_uid}",
                        code=ErrCode.UNEXPECTED,
                        ctx=get_step_ctx(
                            {
                                "video.name": video.name,
                                "segment.uid": seg_uid,
                            }
                        ),
                    )

                if not seg.output_path:
                    raise CutMindError(
                        f"Segment sans chemin source : {seg.uid}",
                        code=ErrCode.UNEXPECTED,
                        ctx=get_step_ctx(
                            {
                                "segment.uid": seg.uid,
                            }
                        ),
                    )

                src_abs = Path(seg.output_path).resolve()

                dst_final = (CUTMIND_BASEDIR / safe_name / Path(dst_rel).name).resolve()

                logger.debug(
                    "🔍 Segment %s → Source : %s",
                    seg.uid,
                    src_abs,
                )

                logger.debug(
                    "🔍 Segment %s → Destination finale : %s",
                    seg.uid,
                    dst_final,
                )

                # --------------------------------------------------------------
                # IMPORTANT :
                # Le fichier est déjà exactement à sa destination.
                #
                # Il ne faut surtout pas :
                #   source -> temp -> destination -> suppression source
                #
                # puisque source == destination provoquerait la suppression
                # du fichier fraîchement finalisé.
                #
                # L'opération est considérée comme réussie/idempotente.
                # --------------------------------------------------------------
                if src_abs == dst_final:
                    already_in_place += 1

                    logger.info(
                        "📍 Segment %s déjà à destination : %s",
                        seg.uid,
                        dst_final,
                    )
                    continue

                dst_temp = dst_final.with_suffix(dst_final.suffix + ".__moving__")

                logger.debug(
                    "🔍 Segment %s → Destination temp : %s",
                    seg.uid,
                    dst_temp,
                )

                # Vérification source anti-corruption / anti-FUSE.
                safe_file_check(src_abs, logger)

                dst_final.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                logger.debug(
                    "⏳ Copie %s -> %s",
                    src_abs,
                    dst_temp,
                )

                shutil.copy2(
                    src_abs,
                    dst_temp,
                )

                # Garantit l'écriture du fichier temporaire sur disque.
                with open(dst_temp, "rb") as tmpf:
                    os.fsync(tmpf.fileno())

                prepared.append(
                    (
                        src_abs,
                        dst_temp,
                        dst_final,
                    )
                )

            # Le volume doit être calculé avant le COMMIT,
            # puisque les sources seront supprimées ensuite.
            total_size_bytes = sum(src_abs.stat().st_size for src_abs, _, _ in prepared)

            # ------------------------------------------------------------------
            # Phase COMMIT
            # ------------------------------------------------------------------
            for src_abs, dst_temp, dst_final in prepared:
                logger.debug(
                    "🔄 Commit %s -> %s",
                    dst_temp,
                    dst_final,
                )

                os.replace(
                    dst_temp,
                    dst_final,
                )

                # --------------------------------------------------------------
                # Deuxième garde volontairement redondante.
                #
                # Une suppression filesystem ne doit JAMAIS pouvoir supprimer
                # le fichier de destination.
                # --------------------------------------------------------------
                if src_abs != dst_final and src_abs.exists():
                    os.remove(src_abs)

            moved_count = len(prepared)
            self._cleanup_source_roots(
                prepared=prepared,
                logger=logger,
            )
            logger.info(
                "✅ Déplacement réussi : %s (%d déplacé(s), %d déjà en place)",
                video.name,
                moved_count,
                already_in_place,
            )

            self.log_summary(
                video=video,
                prepared=prepared,
                already_in_place=already_in_place,
                total_size_bytes=total_size_bytes,
                logger=logger,
            )

            return True

        except CutMindError as err:
            self._cleanup(prepared)

            raise err.with_context(
                get_step_ctx(
                    {
                        "video.name": video.name,
                    }
                )
            ) from err

        except Exception as exc:
            self._cleanup(prepared)

            raise CutMindError(
                "❌ Échec déplacement vidéo.",
                code=ErrCode.UNEXPECTED,
                ctx=get_step_ctx(
                    {
                        "video.name": video.name,
                    }
                ),
            ) from exc

    def log_summary(
        self,
        video: Video,
        prepared: list[tuple[Path, Path, Path]],
        already_in_place: int,
        total_size_bytes: int,
        logger: LoggerProtocol | None = None,
    ) -> None:
        """Log un résumé coloré des fichiers déplacés."""
        logger = ensure_logger(logger, __name__)

        moved_count = len(prepared)
        total_count = moved_count + already_in_place
        total_size_mb = total_size_bytes / (1024 * 1024)

        if prepared:
            destination: Path | None = prepared[0][2].parent
        elif video.name:
            destination = (CUTMIND_BASEDIR / sanitize(video.name)).resolve()
        else:
            destination = None

        logger.info(
            "%s📦 Résumé déplacement : %s%s%s",
            COLOR_PURPLE,
            COLOR_CYAN,
            video.name,
            COLOR_RESET,
        )

        logger.info(
            "%s📌 Traités         : %s%d%s",
            COLOR_BLUE,
            COLOR_GREEN if total_count > 0 else COLOR_RED,
            total_count,
            COLOR_RESET,
        )

        logger.info(
            "%s📌 Déplacés        : %s%d%s",
            COLOR_BLUE,
            COLOR_GREEN,
            moved_count,
            COLOR_RESET,
        )

        logger.info(
            "%s📌 Déjà en place   : %s%d%s",
            COLOR_BLUE,
            COLOR_GREEN,
            already_in_place,
            COLOR_RESET,
        )

        logger.info(
            "%s📌 Volume déplacé  : %s%.2f MB%s",
            COLOR_BLUE,
            COLOR_GREEN,
            total_size_mb,
            COLOR_RESET,
        )

        logger.info(
            "%s📌 Destination     : %s%s%s",
            COLOR_BLUE,
            COLOR_GREEN if destination is not None else COLOR_RED,
            str(destination) if destination is not None else "N/A",
            COLOR_RESET,
        )

    @staticmethod
    def safe_copy(
        src: Path,
        dst: Path,
    ) -> None:
        """Copie un fichier vers une destination."""
        try:
            dst.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            shutil.copy2(
                src,
                dst,
            )

        except Exception as err:
            raise CutMindError(
                "❌ Échec déplacement vidéo.",
                code=ErrCode.UNEXPECTED,
                ctx=get_step_ctx(
                    {
                        "src": src,
                        "dst": dst,
                    }
                ),
            ) from err

    @staticmethod
    def _cleanup(
        prepared: list[tuple[Path, Path, Path]],
    ) -> None:
        """Supprime les fichiers temporaires laissés après un échec."""
        for _, dst_temp, _ in prepared:
            try:
                if dst_temp.exists():
                    dst_temp.unlink()

            except Exception as err:
                raise CutMindError(
                    "❌ Échec nettoyage après échec déplacement.",
                    code=ErrCode.UNEXPECTED,
                    ctx=get_step_ctx(
                        {
                            "dst_temp": dst_temp,
                        }
                    ),
                ) from err

    @staticmethod
    def safe_replace(
        src: Path,
        dst: Path,
        logger: LoggerProtocol | None = None,
    ) -> None:
        """
        Remplace un fichier même entre systèmes de fichiers différents.

        Copie -> fsync -> rename atomique -> suppression source.

        Si source et destination désignent le même chemin, l'opération
        est considérée comme déjà réalisée.
        """
        logger = ensure_logger(logger, __name__)

        move_id = uuid.uuid4().hex[:8]

        src = src.resolve()
        dst = dst.resolve()

        logger.debug(
            "MOVE[%s] start | src=%s | dst=%s",
            move_id,
            src,
            dst,
        )

        # ------------------------------------------------------------------
        # Garde principale contre l'auto-suppression.
        # ------------------------------------------------------------------
        if src == dst:
            logger.debug(
                "MOVE[%s] skipped | source déjà à destination : %s",
                move_id,
                src,
            )
            return

        logger.debug(
            "⏳ Déplacement sécurisé %s -> %s",
            src,
            dst,
        )

        safe_file_check(
            src,
            logger=logger,
        )

        tmp_path = dst.with_suffix(dst.suffix + ".__moving__")

        try:
            dst.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            # Copie sécurisée vers le temporaire.
            FileMover.safe_copy(
                src,
                tmp_path,
            )

            # Garantit l'écriture du temporaire avant remplacement.
            with open(tmp_path, "rb") as tmpf:
                os.fsync(tmpf.fileno())

            # Remplacement atomique.
            os.replace(
                tmp_path,
                dst,
            )

            # --------------------------------------------------------------
            # Deuxième garde destructive.
            # --------------------------------------------------------------
            if src != dst and src.exists():
                os.remove(src)

            logger.debug(
                "MOVE[%s] done",
                move_id,
            )

        except Exception as exc:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()

            except Exception as cleanup_exc:
                raise CutMindError(
                    "❌ Échec cleanup.",
                    code=ErrCode.UNEXPECTED,
                    ctx=get_step_ctx(
                        {
                            "tmp_path": tmp_path,
                        }
                    ),
                ) from cleanup_exc

            raise CutMindError(
                "❌ Échec déplacement sécurisé.",
                code=ErrCode.UNEXPECTED,
                ctx=get_step_ctx(
                    {
                        "src": src,
                        "dst": dst,
                    }
                ),
            ) from exc

    @staticmethod
    def _find_cleanup_root(source: Path) -> Path | None:
        """Trouve la racine de nettoyage correspondant au chemin source."""
        source = source.resolve()

        for configured_root in CLEANABLE_ROOTS:
            root = configured_root.resolve()

            if source.is_relative_to(root):
                return root

        return None

    @staticmethod
    def _cleanup_source_roots(
        prepared: list[tuple[Path, Path, Path]],
        logger: LoggerProtocol,
    ) -> None:
        """Nettoie les dossiers vides dans les racines ayant perdu des fichiers."""
        cleanup_roots: set[Path] = set()

        for src_abs, _, _ in prepared:
            source = src_abs.resolve()

            for configured_root in CLEANABLE_ROOTS:
                root = configured_root.resolve()

                if source.is_relative_to(root):
                    cleanup_roots.add(root)
                    break
            else:
                logger.debug(
                    "🧹 Source hors des racines de nettoyage : %s",
                    source,
                )

        for root in cleanup_roots:
            logger.debug(
                "🧹 Nettoyage des dossiers vides dans : %s",
                root,
            )

            deleted_count = remove_empty_dirs(
                root,
                logger=logger,
            )

            logger.debug(
                "🧹 Nettoyage terminé : %s (%d dossier(s) supprimé(s))",
                root,
                deleted_count,
            )
