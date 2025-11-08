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
from cutmind.models.cursor_protocol import DictCursorProtocol
from cutmind.models.db_models import Segment, Video
from shared.utils.logger import get_logger

logger = get_logger(__name__)


# =====================================================================
# 🎯 Repository principal
# =====================================================================
class CutMindRepository:
    """Gestion centralisée des accès à la base de données CutMind."""

    # -------------------------------------------------------------
    # 🔍 Vérifie si une vidéo existe déjà
    # -------------------------------------------------------------
    def video_exists(self, uid: str) -> bool:
        with db_conn() as conn:
            with get_dict_cursor(conn) as cur:
                safe_execute_dict(cur, "SELECT COUNT(*) AS count FROM videos WHERE uid=%s", (uid,))
                row = cur.fetchone()
                exists = bool(row and row["count"] > 0)
                logger.debug("🔍 video_exists(%s) → %s", uid, exists)
                return exists

    # -------------------------------------------------------------
    # 📥 Insertion vidéo + segments
    # -------------------------------------------------------------
    def insert_video_with_segments(self, video: Video) -> int:
        """Insère une vidéo et ses segments associés."""
        with db_conn() as conn:
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
                )
                video_id = cur.lastrowid
                logger.debug("🎬 Vidéo insérée id=%s uid=%s", video_id, video.uid)

                # --- Segments ---
                if not video_id:
                    raise ValueError("Erreur insertion vidéo : ID non retourné.")
                for seg in video.segments:
                    seg.video_id = video_id
                    seg_id = self._insert_segment(cur, seg)
                    if seg.keywords:
                        self.insert_keywords_for_segment(cur, seg_id, seg.keywords)

                conn.commit()
                return video_id

    # -------------------------------------------------------------
    # 🧩 Insertion d’un segment (interne)
    # -------------------------------------------------------------
    def _insert_segment(self, cur: DictCursorProtocol, seg: Segment) -> int:
        safe_execute_dict(
            cur,
            """
            INSERT INTO segments (
                uid, video_id, start, end, duration, status,
                confidence, description, fps, resolution, codec,
                bitrate, filesize_mb, filename_predicted, output_path,
                source_flow, processed_by
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            ),
        )
        seg_id = cur.lastrowid
        if not seg_id:
            raise ValueError("Erreur insertion segment : ID non retourné.")
        logger.debug("🧩 Segment inséré id=%d uid=%s", seg_id, seg.uid)
        return seg_id

    # -------------------------------------------------------------
    # 🔗 Insertion des mots-clés liés à un segment
    # -------------------------------------------------------------
    def insert_keywords_for_segment(self, cur: DictCursorProtocol, segment_id: int, keywords: list[str]) -> None:
        """Insère les mots-clés d’un segment (en évitant les doublons)."""
        for kw in keywords:
            kw_clean = kw.strip().lower()
            if not kw_clean:
                continue

            safe_execute_dict(cur, "SELECT id FROM keywords WHERE keyword=%s", (kw_clean,))
            row = cur.fetchone()
            if row:
                kw_id = row["id"]
            else:
                safe_execute_dict(cur, "INSERT INTO keywords (keyword) VALUES (%s)", (kw_clean,))
                kw_id = cur.lastrowid

            safe_execute_dict(
                cur,
                "INSERT INTO segment_keywords (segment_id, keyword_id) VALUES (%s, %s)",
                (segment_id, kw_id),
            )
        logger.debug("🏷️ %d mots-clés insérés pour segment_id=%d", len(keywords), segment_id)

    # -------------------------------------------------------------
    # 🔎 Récupération d’une vidéo complète (segments + keywords)
    # -------------------------------------------------------------
    def get_video_with_segments(self, video_uid: str) -> Video | None:
        """Retourne un objet Video complet (avec ses segments et mots-clés)."""
        with db_conn() as conn:
            with get_dict_cursor(conn) as cur:
                safe_execute_dict(cur, "SELECT * FROM videos WHERE uid=%s", (video_uid,))
                video_row = cur.fetchone()
                if not video_row:
                    return None

                video = Video(**{k: video_row[k] for k in video_row if k in Video.__annotations__})
                video.id = video_row["id"]

                # --- Segments ---
                safe_execute_dict(cur, "SELECT * FROM segments WHERE video_id=%s", (video.id,))
                seg_rows = cur.fetchall()
                for seg_row in seg_rows:
                    seg = Segment(**{k: seg_row[k] for k in seg_row if k in Segment.__annotations__})
                    seg.id = seg_row["id"]
                    if not seg.id:
                        continue
                    seg.keywords = self.get_keywords_for_segment(cur, seg.id)
                    video.segments.append(seg)

                return video

    def get_videos_by_status(self, status: str) -> list[Video]:
        """
        Retourne toutes les vidéos (avec leurs segments et mots-clés)
        correspondant à un statut donné.

        Args:
            status: Statut de la vidéo (ex: 'manual_review', 'validated', 'processing_router').

        Returns:
            list[Video]: liste d'objets Video complets avec leurs segments.
        """
        with db_conn() as conn:
            with get_dict_cursor(conn) as cur:
                safe_execute_dict(cur, "SELECT * FROM videos WHERE status=%s", (status,))
                video_rows = cur.fetchall()
                videos: list[Video] = []

                for video_row in video_rows:
                    video = Video(**{k: video_row[k] for k in video_row if k in Video.__annotations__})
                    video.id = video_row["id"]

                    # --- Segments associés ---
                    safe_execute_dict(cur, "SELECT * FROM segments WHERE video_id=%s", (video.id,))
                    seg_rows = cur.fetchall()
                    for seg_row in seg_rows:
                        seg = Segment(**{k: seg_row[k] for k in seg_row if k in Segment.__annotations__})
                        seg.id = seg_row["id"]
                        if not seg.id:
                            continue
                        seg.keywords = self.get_keywords_for_segment(cur, seg.id)
                        video.segments.append(seg)

                    videos.append(video)

                return videos

    def get_segments_by_status(self, status: str) -> list[Segment]:
        """Retourne tous les segments d’un statut donné."""
        with db_conn() as conn:
            with get_dict_cursor(conn) as cur:
                safe_execute_dict(cur, "SELECT * FROM segments WHERE status=%s", (status,))
                seg_rows = cur.fetchall()
                return [Segment(**{k: row[k] for k in row if k in Segment.__annotations__}) for row in seg_rows]

    def get_segments_pending_review(self) -> list[Segment]:
        """Retourne tous les segments en attente de validation manuelle."""
        statuses = ("manual_review", "pending_check", "manual_review_pending")
        with db_conn() as conn:
            with get_dict_cursor(conn) as cur:
                placeholders = ",".join(["%s"] * len(statuses))
                query = f"SELECT * FROM segments WHERE status IN ({placeholders})"
                safe_execute_dict(cur, query, statuses)
                seg_rows = cur.fetchall()
                return [Segment(**{k: row[k] for k in row if k in Segment.__annotations__}) for row in seg_rows]

    def get_segment_by_uid(self, uid: str) -> Segment | None:
        """Retourne un segment spécifique par son UID."""
        with db_conn() as conn:
            with get_dict_cursor(conn) as cur:
                safe_execute_dict(cur, "SELECT * FROM segments WHERE uid=%s", (uid,))
                row = cur.fetchone()
                if not row:
                    return None
                return Segment(**{k: row[k] for k in row if k in Segment.__annotations__})

    # -------------------------------------------------------------
    # 🏷️ Récupération des mots-clés d’un segment
    # -------------------------------------------------------------
    def get_keywords_for_segment(self, cur: DictCursorProtocol, segment_id: int) -> list[str]:
        safe_execute_dict(
            cur,
            """
            SELECT k.keyword
            FROM keywords k
            JOIN segment_keywords sk ON sk.keyword_id = k.id
            WHERE sk.segment_id = %s
            """,
            (segment_id,),
        )
        rows = cur.fetchall()
        return [r["keyword"] for r in rows]

    def get_nonstandard_videos(self, limit_videos: int = 10) -> list[str]:
        """
        Retourne les UID de vidéos 'validated' contenant au moins un segment
        dont la résolution ou les FPS sont inférieurs aux standards (1920x1080, 60fps).
        """
        with db_conn() as conn:
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
                )
                rows = cur.fetchall()
                return [row["uid"] for row in rows if "uid" in row]

    # -------------------------------------------------------------
    # 🔄 Mise à jour d’un segment
    # -------------------------------------------------------------
    def update_segment_validation(self, seg: Segment, conn: Connection | None = None) -> None:
        """Mise à jour suite à validation automatique ou manuelle."""
        if conn is None:
            with db_conn() as conn:
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
                            last_updated=NOW()
                        WHERE uid=%s
                        """,
                        (
                            seg.status,
                            seg.source_flow,
                            seg.confidence,
                            seg.description,
                            seg.output_path,
                            seg.uid,
                        ),
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
                        last_updated=NOW()
                    WHERE uid=%s
                    """,
                    (
                        seg.status,
                        seg.source_flow,
                        seg.confidence,
                        seg.description,
                        seg.output_path,
                        seg.uid,
                    ),
                )
                logger.debug(
                    "🧩 UPDATE validation (in-transaction) → uid=%s | status=%s | flow=%s | output=%s",
                    seg.uid,
                    seg.status,
                    seg.source_flow,
                    seg.output_path,
                )

    def update_segment_postprocess(self, seg: Segment) -> None:
        """Mise à jour après traitement ComfyUI."""
        with db_conn() as conn:
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
                        seg.uid,
                    ),
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
    def update_video(self, video: Video, conn: Connection | None = None) -> None:
        """Met à jour le statut ou autres champs d’une vidéo."""
        if conn is None:
            with db_conn() as conn:
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
                )
                logger.debug("🎞️ UPDATE video (in-transaction) → uid=%s | status=%s", video.uid, video.status)

    # ------------------------------------------------------------------
    # 🔹 SUPPRESSION
    # ------------------------------------------------------------------
    def delete_segment_by_uid(self, seg_uid: str) -> bool:
        """Supprime un segment spécifique."""
        with db_conn() as conn:
            with get_dict_cursor(conn) as cur:
                safe_execute_dict(cur, "DELETE FROM segments WHERE uid=%s", (seg_uid,))
                conn.commit()
                logger.info("🗑️ Segment supprimé uid=%s", seg_uid)
                return True

    # ------------------------------------------------------------------
    # 🧱 CONTEXTE TRANSACTIONNEL (global)
    # ------------------------------------------------------------------
    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        """
        Contexte transactionnel global basé sur db_conn().
        Permet d'exécuter plusieurs opérations du repository
        dans une seule et même transaction SQL.

        Exemple :
            with repo.transaction() as conn:
                repo.update_segment_validation(seg, conn)
                repo.update_video(video, conn)
        """
        with db_conn() as conn:
            try:
                logger.debug("🧾 Début transaction SQL (repo)")
                yield conn
                logger.debug("✅ Commit transaction SQL (repo)")
            except Exception as err:
                logger.exception("❌ Rollback transaction SQL : %s", err)
                raise
