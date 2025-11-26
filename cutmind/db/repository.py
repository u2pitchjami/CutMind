"""
CutMind Repository (v3.3)
=========================

Couche d’accès à la base de données MariaDB pour le projet CutMind.

- Gestion des vidéos et segments
- Insertion / lecture / mise à jour cohérente
- Basé sur db_conn() et safe_execute_dict() pour sécurité et logs

Dépendances :
-------------
from cutmind.db.db_connection import db_conn, get_dict_cursor
from cutmind.sql.db_utils import safe_execute_dict
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from pymysql.connections import Connection

from cutmind.db.db_connection import db_conn, get_dict_cursor
from cutmind.db.db_utils import safe_execute_dict
from cutmind.models_cm.cursor_protocol import DictCursorProtocol
from cutmind.models_cm.db_models import Segment, Video
from shared.utils.logger import LoggerProtocol, ensure_logger, with_child_logger


# =====================================================================
# 🎯 Repository principal
# =====================================================================
class CutMindRepository:
    """Gestion centralisée des accès à la base de données CutMind."""

    # -------------------------------------------------------------
    # 🔍 Vérifie si une vidéo existe déjà
    # -------------------------------------------------------------
    @with_child_logger
    def video_exists(self, uid: str, logger: LoggerProtocol | None = None) -> bool:
        logger = ensure_logger(logger, __name__)
        with db_conn(logger=logger) as conn:
            with get_dict_cursor(conn) as cur:
                safe_execute_dict(cur, "SELECT COUNT(*) AS count FROM videos WHERE uid=%s", (uid,), logger=logger)
                row = cur.fetchone()
                exists = bool(row and row["count"] > 0)
                logger.debug("🔍 video_exists(%s) → %s", uid, exists)
                return exists

    def video_exists_by_video_path(self, video_path: str) -> int | None:
        with db_conn() as conn:
            with get_dict_cursor(conn) as cur:
                safe_execute_dict(cur, "SELECT COUNT(*) AS count FROM videos WHERE video_path=%s", (video_path,))
                row = cur.fetchone()
                return row["id"] if row else None

    # -------------------------------------------------------------
    # 📥 Insertion vidéo + segments
    # -------------------------------------------------------------
    @with_child_logger
    def insert_video_with_segments(self, video: Video, logger: LoggerProtocol | None = None) -> int:
        """Insère une vidéo et ses segments associés."""
        logger = ensure_logger(logger, __name__)
        with db_conn(logger=logger) as conn:
            with get_dict_cursor(conn) as cur:
                # --- Vidéo ---
                safe_execute_dict(
                    cur,
                    """
                    INSERT INTO videos (
                        uid, name, duration, fps, resolution, codec,
                        bitrate, filesize_mb, status, origin
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        video.uid,
                        video.name,
                        video.duration,
                        video.fps,
                        video.resolution,
                        video.codec,
                        video.bitrate,
                        video.filesize_mb,
                        video.status,
                        video.origin,
                    ),
                    logger=logger,
                )
                video_id = cur.lastrowid
                logger.debug("🎬 Vidéo insérée id=%s uid=%s", video_id, video.uid)

                # --- Segments ---
                if not video_id:
                    raise ValueError("Erreur insertion vidéo : ID non retourné.")
                for seg in video.segments:
                    seg.video_id = video_id
                    seg_id = self._insert_segment(seg, cur, logger=logger)
                    if seg.keywords:
                        self.insert_keywords_for_segment(cur, seg_id, seg.keywords, logger=logger)

                conn.commit()
                return video_id

    # -------------------------------------------------------------
    # 🧩 Insertion d’un segment (interne)
    # -------------------------------------------------------------
    @with_child_logger
    def _insert_segment(
        self,
        seg: Segment,
        cur: DictCursorProtocol | None = None,
        logger: LoggerProtocol | None = None,
    ) -> int:
        logger = ensure_logger(logger, __name__)

        # --- Mode autonome : on ouvre la connexion ---
        if cur is None:
            with db_conn(logger=logger) as conn:
                with get_dict_cursor(conn) as cur2:
                    seg_id = self._insert_segment(seg, cur=cur2, logger=logger)
                    return seg_id

        # --- Mode manuel : on utilise le cursor fourni ---
        safe_execute_dict(
            cur,
            """
            INSERT INTO segments (
                uid, video_id, start, end, duration, status,
                confidence, description, fps, resolution, codec,
                bitrate, filesize_mb, filename_predicted, output_path,
                source_flow, processed_by, ai_model
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                seg.uid,
                seg.video_id,
                seg.start,
                seg.end,
                seg.duration,
                seg.status,
                seg.confidence,
                seg.description,
                seg.fps,
                seg.resolution,
                seg.codec,
                seg.bitrate,
                seg.filesize_mb,
                seg.filename_predicted,
                seg.output_path,
                seg.source_flow,
                seg.processed_by,
                seg.ai_model,
            ),
            logger=logger,
        )
        if not cur.lastrowid:
            raise ValueError("Erreur insertion segment : ID non retourné.")
        seg_id = cur.lastrowid
        if not seg_id:
            raise ValueError("Erreur insertion segment : ID non retourné.")

        logger.debug("🧩 Segment inséré id=%d uid=%s", seg_id, seg.uid)
        return seg_id

    # -------------------------------------------------------------
    # 🔗 Insertion des mots-clés liés à un segment
    # -------------------------------------------------------------
    @with_child_logger
    def insert_keywords_for_segment(
        self, cur: DictCursorProtocol, segment_id: int, keywords: list[str], logger: LoggerProtocol | None = None
    ) -> None:
        """Insère les mots-clés d’un segment (en évitant les doublons)."""
        logger = ensure_logger(logger, __name__)
        for kw in keywords:
            kw_clean = kw.strip().lower()
            if not kw_clean:
                continue

            safe_execute_dict(cur, "SELECT id FROM keywords WHERE keyword=%s", (kw_clean,), logger=logger)
            row = cur.fetchone()
            if row:
                kw_id = row["id"]
            else:
                safe_execute_dict(cur, "INSERT INTO keywords (keyword) VALUES (%s)", (kw_clean,), logger=logger)
                kw_id = cur.lastrowid

            safe_execute_dict(
                cur,
                "INSERT INTO segment_keywords (segment_id, keyword_id) VALUES (%s, %s)",
                (segment_id, kw_id),
                logger=logger,
            )
        logger.debug("🏷️ %d mots-clés insérés pour segment_id=%d", len(keywords), segment_id)

    @with_child_logger
    def insert_keywords_standalone(
        self, segment_id: int, keywords: list[str], logger: LoggerProtocol | None = None
    ) -> None:
        logger = ensure_logger(logger, __name__)
        with db_conn(logger=logger) as conn:
            with get_dict_cursor(conn) as cur:
                self.insert_keywords_for_segment(cur, segment_id, keywords, logger=logger)
            conn.commit()

    # -------------------------------------------------------------
    # 🔎 Récupération d’une vidéo complète (segments + keywords)
    # -------------------------------------------------------------
    @with_child_logger
    def get_video_with_segments(
        self,
        video_uid: str | None = None,
        video_id: int | None = None,
        logger: LoggerProtocol | None = None,
    ) -> Video | None:
        """
        Retourne un objet Video complet (avec ses segments et mots-clés).
        Peut recevoir soit video_uid, soit video_id.
        """
        logger = ensure_logger(logger, __name__)

        if video_id is None and video_uid is None:
            raise ValueError("video_uid ou video_id doit être fourni")

        with db_conn(logger=logger) as conn:
            with get_dict_cursor(conn) as cur:
                # --- Identifier la ligne vidéo ---
                if video_id is not None:
                    safe_execute_dict(cur, "SELECT * FROM videos WHERE id=%s", (video_id,), logger=logger)
                else:
                    safe_execute_dict(cur, "SELECT * FROM videos WHERE uid=%s", (video_uid,), logger=logger)

                video_row = cur.fetchone()
                if not video_row:
                    return None

                # --- Construction Video ---
                video = Video(**{k: video_row[k] for k in video_row if k in Video.__annotations__})
                video.id = video_row["id"]

                # --- Segments ---
                safe_execute_dict(cur, "SELECT * FROM segments WHERE video_id=%s", (video.id,), logger=logger)
                seg_rows = cur.fetchall()

                for seg_row in seg_rows:
                    seg = Segment(**{k: seg_row[k] for k in seg_row if k in Segment.__annotations__})
                    seg.id = seg_row["id"]

                    if seg.id:
                        seg.keywords = self.get_keywords_for_segment(cur, seg.id)

                    video.segments.append(seg)

                return video

    @with_child_logger
    def get_videos_by_status(self, status: str, logger: LoggerProtocol | None = None) -> list[Video]:
        """
        Retourne toutes les vidéos (avec leurs segments et mots-clés)
        correspondant à un statut donné.

        Args:
            status: Statut de la vidéo (ex: 'manual_review', 'validated', 'processing_router').

        Returns:
            list[Video]: liste d'objets Video complets avec leurs segments.
        """
        logger = ensure_logger(logger, __name__)
        with db_conn(logger=logger) as conn:
            with get_dict_cursor(conn) as cur:
                safe_execute_dict(cur, "SELECT * FROM videos WHERE status=%s", (status,), logger=logger)
                video_rows = cur.fetchall()
                videos: list[Video] = []

                for video_row in video_rows:
                    video = Video(**{k: video_row[k] for k in video_row if k in Video.__annotations__})
                    video.id = video_row["id"]

                    # --- Segments associés ---
                    safe_execute_dict(cur, "SELECT * FROM segments WHERE video_id=%s", (video.id,), logger=logger)
                    seg_rows = cur.fetchall()
                    for seg_row in seg_rows:
                        seg = Segment(**{k: seg_row[k] for k in seg_row if k in Segment.__annotations__})
                        seg.id = seg_row["id"]
                        if not seg.id:
                            continue
                        seg.keywords = self.get_keywords_for_segment(cur, seg.id, logger=logger)
                        video.segments.append(seg)

                    videos.append(video)

                return videos

    @with_child_logger
    def get_video_id_from_segment_id(self, segment_id: int, logger: LoggerProtocol | None = None) -> int | None:
        """
        Retourne video_id à partir d'un id de segment.
        """
        logger = ensure_logger(logger, __name__)
        with db_conn(logger=logger) as conn:
            with get_dict_cursor(conn) as cur:
                safe_execute_dict(cur, "SELECT video_id FROM segments WHERE id=%s", (segment_id,), logger=logger)
                row = cur.fetchone()
                return row["video_id"] if row else None

    @with_child_logger
    def get_segments_by_status(self, status: str, logger: LoggerProtocol | None = None) -> list[Segment]:
        """Retourne tous les segments d’un statut donné."""
        logger = ensure_logger(logger, __name__)
        with db_conn(logger=logger) as conn:
            with get_dict_cursor(conn) as cur:
                safe_execute_dict(cur, "SELECT * FROM segments WHERE status=%s", (status,), logger=logger)
                seg_rows = cur.fetchall()
                return [Segment(**{k: row[k] for k in row if k in Segment.__annotations__}) for row in seg_rows]

    @with_child_logger
    def get_segments_pending_review(self, logger: LoggerProtocol | None = None) -> list[Segment]:
        """Retourne tous les segments en attente de validation manuelle."""
        logger = ensure_logger(logger, __name__)
        statuses = ("manual_review", "pending_check", "manual_review_pending")
        with db_conn(logger=logger) as conn:
            with get_dict_cursor(conn) as cur:
                placeholders = ",".join(["%s"] * len(statuses))
                query = f"SELECT * FROM segments WHERE status IN ({placeholders})"
                safe_execute_dict(cur, query, statuses, logger=logger)
                seg_rows = cur.fetchall()
                return [Segment(**{k: row[k] for k in row if k in Segment.__annotations__}) for row in seg_rows]

    @with_child_logger
    def get_segment_by_id(self, segment_id: int, logger: LoggerProtocol | None = None) -> Segment | None:
        logger = ensure_logger(logger, __name__)
        query = "SELECT * FROM segments WHERE id = %s LIMIT 1"
        try:
            with db_conn(logger=logger) as conn:
                with get_dict_cursor(conn) as cur:
                    cur.execute(query, (segment_id,))
                    row = cur.fetchone()
                    if not row:
                        return None
                    return Segment.from_row(row)
        except Exception as err:
            logger.error("❌ Erreur get_segment_by_id(%s) : %s", segment_id, err)
            return None

    @with_child_logger
    def get_segment_by_uid(self, uid: str, logger: LoggerProtocol | None = None) -> Segment | None:
        """Retourne un segment spécifique par son UID."""
        logger = ensure_logger(logger, __name__)
        with db_conn(logger=logger) as conn:
            with get_dict_cursor(conn) as cur:
                safe_execute_dict(cur, "SELECT * FROM segments WHERE uid=%s", (uid,), logger=logger)
                row = cur.fetchone()
                if not row:
                    return None
                return Segment(**{k: row[k] for k in row if k in Segment.__annotations__})

    @with_child_logger
    def get_segments_by_category(self, category: str, logger: LoggerProtocol | None = None) -> list[Segment]:
        """
        Récupère tous les segments 'enhanced' d'une catégorie donnée.
        """
        logger = ensure_logger(logger, __name__)
        with db_conn(logger=logger) as conn:
            with get_dict_cursor(conn) as cur:
                safe_execute_dict(
                    cur,
                    """
                    SELECT s.*
                    FROM segments s
                    WHERE s.status = 'enhanced'
                    AND s.category = %s
                    ORDER BY s.created_at DESC
                    """,
                    (category,),
                    logger=logger,
                )
                rows = cur.fetchall()
                return [Segment.from_row(row) for row in rows]

    # -------------------------------------------------------------
    # 🏷️ Récupération des mots-clés d’un segment
    # -------------------------------------------------------------
    @with_child_logger
    def get_keywords_for_segment(
        self, cur: DictCursorProtocol, segment_id: int, logger: LoggerProtocol | None = None
    ) -> list[str]:
        logger = ensure_logger(logger, __name__)
        safe_execute_dict(
            cur,
            """
            SELECT k.keyword
            FROM keywords k
            JOIN segment_keywords sk ON sk.keyword_id = k.id
            WHERE sk.segment_id = %s
            """,
            (segment_id,),
            logger=logger,
        )
        rows = cur.fetchall()
        return [r["keyword"] for r in rows]

    @with_child_logger
    def get_nonstandard_videos(self, limit_videos: int = 10, logger: LoggerProtocol | None = None) -> list[str]:
        """
        Retourne les UID de vidéos 'validated' contenant au moins un segment
        dont la résolution ou les FPS sont inférieurs aux standards (1920x1080, 60fps).
        """
        logger = ensure_logger(logger, __name__)
        with db_conn(logger=logger) as conn:
            with get_dict_cursor(conn) as cur:
                safe_execute_dict(
                    cur,
                    """
                    SELECT DISTINCT v.uid
                    FROM videos v
                    JOIN segments s ON v.id = s.video_id
                    WHERE
                        v.status = 'validated'
                        AND s.status = 'validated'
                        AND (
                            CAST(SUBSTRING_INDEX(s.resolution, 'x', 1) AS UNSIGNED) < 1920
                            OR CAST(SUBSTRING_INDEX(s.resolution, 'x', -1) AS UNSIGNED) < 1080
                            OR s.fps IS NULL
                            OR s.fps <> 60.0
                        )
                    ORDER BY RAND()
                    LIMIT %s
                    """,
                    (limit_videos,),
                    logger=logger,
                )
                rows = cur.fetchall()
                return [row["uid"] for row in rows if "uid" in row]

    @with_child_logger
    def get_standard_videos(self, limit_videos: int = 10, logger: LoggerProtocol | None = None) -> list[str]:
        """
        Retourne les UID de vidéos 'validated' dont tous les segments sont déjà en 1080p 60fps.
        """
        logger = ensure_logger(logger, __name__)
        with db_conn(logger=logger) as conn:
            with get_dict_cursor(conn) as cur:
                safe_execute_dict(
                    cur,
                    """
                    SELECT DISTINCT v.uid
                    FROM videos v
                    JOIN segments s ON v.id = s.video_id
                    WHERE
                        v.status = 'validated'
                        AND s.status = 'validated'
                        AND (
                            CAST(SUBSTRING_INDEX(s.resolution, 'x', 1) AS UNSIGNED) = 1920
                            AND CAST(SUBSTRING_INDEX(s.resolution, 'x', -1) AS UNSIGNED) = 1080
                            AND s.fps = 60.0
                        )
                    ORDER BY RAND()
                    LIMIT %s
                    """,
                    (limit_videos,),
                    logger=logger,
                )
                rows = cur.fetchall()
                return [row["uid"] for row in rows if "uid" in row]

    # -------------------------------------------------------------
    # 🔄 Mise à jour d’un segment
    # -------------------------------------------------------------
    @with_child_logger
    def update_segment_validation(
        self, seg: Segment, conn: Connection | None = None, logger: LoggerProtocol | None = None
    ) -> None:
        """Mise à jour suite à validation automatique ou manuelle."""
        logger = ensure_logger(logger, __name__)
        if conn is None:
            with db_conn(logger=logger) as conn:
                with get_dict_cursor(conn) as cur:
                    safe_execute_dict(
                        cur,
                        """
                        UPDATE segments
                        SET status=%s,
                            source_flow=%s,
                            confidence=%s,
                            description=%s,
                            output_path=%s,
                            category=%s,
                            ai_model=%s,
                            tags=%s,
                            last_updated=NOW()
                        WHERE uid=%s
                        """,
                        (
                            seg.status,
                            seg.source_flow,
                            seg.confidence,
                            seg.description,
                            seg.output_path,
                            seg.category,
                            seg.ai_model,
                            seg.tags,
                            seg.uid,
                        ),
                        logger=logger,
                    )
                    conn.commit()
                    logger.debug(
                        "🧩 UPDATE validation → uid=%s | status=%s | flow=%s | output=%s",
                        seg.uid,
                        seg.status,
                        seg.source_flow,
                        seg.output_path,
                    )
        else:
            with get_dict_cursor(conn) as cur:
                safe_execute_dict(
                    cur,
                    """
                    UPDATE segments
                    SET status=%s,
                        source_flow=%s,
                        confidence=%s,
                        description=%s,
                        output_path=%s,
                        category=%s,
                        ai_model=%s,
                        tags=%s,
                        last_updated=NOW()
                    WHERE uid=%s
                    """,
                    (
                        seg.status,
                        seg.source_flow,
                        seg.confidence,
                        seg.description,
                        seg.output_path,
                        seg.category,
                        seg.ai_model,
                        seg.tags,
                        seg.uid,
                    ),
                    logger=logger,
                )
                logger.debug(
                    "🧩 UPDATE validation (in-transaction) → uid=%s | status=%s | flow=%s | output=%s",
                    seg.uid,
                    seg.status,
                    seg.source_flow,
                    seg.output_path,
                )

    @with_child_logger
    def update_segment_postprocess(self, seg: Segment, logger: LoggerProtocol | None = None) -> None:
        """Mise à jour après traitement ComfyUI."""
        logger = ensure_logger(logger, __name__)
        with db_conn(logger=logger) as conn:
            with get_dict_cursor(conn) as cur:
                safe_execute_dict(
                    cur,
                    """
                    UPDATE segments
                    SET resolution=%s,
                        fps=%s,
                        codec=%s,
                        bitrate=%s,
                        filesize_mb=%s,
                        duration=%s,
                        status=%s,
                        source_flow=%s,
                        processed_by=%s,
                        tags=%s,
                        last_updated=NOW()
                    WHERE uid=%s
                    """,
                    (
                        seg.resolution,
                        seg.fps,
                        seg.codec,
                        seg.bitrate,
                        seg.filesize_mb,
                        seg.duration,
                        seg.status,
                        seg.source_flow,
                        seg.processed_by,
                        seg.tags,
                        seg.uid,
                    ),
                    logger=logger,
                )
                conn.commit()
                logger.debug(
                    "🎞️ UPDATE postprocess → uid=%s | res=%s | fps=%.2f | flow=%s",
                    seg.uid,
                    seg.resolution,
                    seg.fps or 0.0,
                    seg.source_flow,
                )

    # -------------------------------------------------------------
    # 🔄 Mise à jour d’une vidéo
    # -------------------------------------------------------------
    @with_child_logger
    def update_video(self, video: Video, conn: Connection | None = None, logger: LoggerProtocol | None = None) -> None:
        """Met à jour le statut ou autres champs d’une vidéo."""
        logger = ensure_logger(logger, __name__)
        if conn is None:
            with db_conn(logger=logger) as conn:
                with get_dict_cursor(conn) as cur:
                    safe_execute_dict(
                        cur,
                        """
                        UPDATE videos
                        SET status=%s,
                            last_updated=NOW()
                        WHERE uid=%s
                        """,
                        (
                            video.status,
                            video.uid,
                        ),
                        logger=logger,
                    )
                    conn.commit()
                    logger.debug("🎞️ UPDATE video DB → uid=%s | status=%s", video.uid, video.status)
        else:
            with get_dict_cursor(conn) as cur:
                safe_execute_dict(
                    cur,
                    """
                    UPDATE videos
                    SET status=%s,
                        last_updated=NOW()
                    WHERE uid=%s
                    """,
                    (
                        video.status,
                        video.uid,
                    ),
                    logger=logger,
                )
                logger.debug("🎞️ UPDATE video (in-transaction) → uid=%s | status=%s", video.uid, video.status)

    # ------------------------------------------------------------------
    # 🔹 SUPPRESSION
    # ------------------------------------------------------------------
    @with_child_logger
    def delete_segment_by_uid(self, seg_uid: str, logger: LoggerProtocol | None = None) -> bool:
        """Supprime un segment spécifique."""
        logger = ensure_logger(logger, __name__)
        with db_conn(logger=logger) as conn:
            with get_dict_cursor(conn) as cur:
                safe_execute_dict(cur, "DELETE FROM segments WHERE uid=%s", (seg_uid,), logger=logger)
                conn.commit()
                logger.info("🗑️ Segment supprimé uid=%s", seg_uid)
                return True

    @with_child_logger
    def delete_segment(self, seg_id: int, logger: LoggerProtocol | None = None) -> None:
        """Supprime un segment et ses mots-clés."""
        logger = ensure_logger(logger, __name__)
        with db_conn(logger=logger) as conn:
            with get_dict_cursor(conn) as cur:
                safe_execute_dict(cur, "DELETE FROM segments WHERE id=%s", (seg_id,), logger=logger)
                safe_execute_dict(cur, "DELETE FROM segment_keywords WHERE segment_id=%s", (seg_id,), logger=logger)
                conn.commit()
        logger.info("🗑️ Segment supprimé : %s", seg_id)

    # ------------------------------------------------------------------
    # 🧱 CONTEXTE TRANSACTIONNEL (global)
    # ------------------------------------------------------------------
    @contextmanager
    @with_child_logger
    def transaction(self, logger: LoggerProtocol | None = None) -> Iterator[Connection]:
        """
        Contexte transactionnel global basé sur db_conn().
        Permet d'exécuter plusieurs opérations du repository
        dans une seule et même transaction SQL.

        Exemple :
            with repo.transaction() as conn:
                repo.update_segment_validation(seg, conn)
                repo.update_video(video, conn)
        """
        logger = ensure_logger(logger, __name__)
        with db_conn(logger=logger) as conn:
            try:
                logger.debug("🧾 Début transaction SQL (repo)")
                yield conn
                logger.debug("✅ Commit transaction SQL (repo)")
            except Exception as err:
                logger.exception("❌ Rollback transaction SQL : %s", err)
                raise
