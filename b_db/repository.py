"""
CutMind Repository (v3.4)
=========================

Couche d’accès à la base de données MariaDB pour le projet CutMind.

- Gestion des vidéos et segments
- Insertion / lecture / mise à jour cohérente
- Basé sur db_conn(logger=self.logger) et safe_execute_dict() pour sécurité et logs
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from pymysql.connections import Connection

from b_db.db_connection import db_conn, get_dict_cursor
from b_db.db_utils import safe_execute_dict, to_db_json
from b_db.models.cursor_protocol import DictCursorProtocol
from d_comfyui_router.models_cr.processed_segment import ProcessedSegment
from e_IA.keywords.frames.frames_hash import SegmentFrameHash
from g_check.histo.processing_histo import ProcessingHistory
from shared.models.db_models import Segment, Video
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.services.video_preparation import VideoPrepared
from shared.status_orchestrator.statuses import OrchestratorStatus
from shared.utils.logger import get_logger


# =====================================================================
# 🎯 Repository principal
# =====================================================================
class CutMindRepository:
    """
    Gestion centralisée des accès à la base de données CutMind.
    """

    def __init__(self) -> None:
        self.logger = get_logger("CutMind-DB")

    # ------------------------------------------------------------------
    # 🧱 Helpers internes génériques
    # ------------------------------------------------------------------
    def _exec_sql(
        self,
        sql: str,
        params: Sequence[Any] | None = None,
        conn: Connection | None = None,
    ) -> None:
        """
        Exécute une requête SQL (INSERT/UPDATE/DELETE) sans retourner de lignes.

        Gère automatiquement la connexion lorsque conn est None.
        """
        try:
            sql_params: tuple[Any, ...] = tuple(params) if params else ()

            if conn is None:
                with db_conn(logger=self.logger) as _conn:
                    with get_dict_cursor(_conn) as cur:
                        safe_execute_dict(cur, sql, sql_params)
                        _conn.commit()
            else:
                with get_dict_cursor(conn) as cur:
                    safe_execute_dict(cur, sql, sql_params)
        except Exception as exc:  # pylint: disable=broad-except
            err_type = type(exc).__name__
            err_msg = str(exc)
            sql_preview = sql[:500] if isinstance(sql, str) else sql

            raise CutMindError(
                "❌ Erreur SQL",
                code=ErrCode.DB,
                ctx=get_step_ctx(
                    {
                        "sql_error_type": err_type,
                        "sql_error": err_msg,
                        "sql": sql_preview,
                        "params": params,
                    }
                ),
            ) from exc

    def _fetch_one(
        self,
        sql: str,
        params: Sequence[Any] | None = None,
    ) -> dict[str, Any] | None:
        """
        Exécute un SELECT et retourne une seule ligne (ou None).
        """
        sql_params: tuple[Any, ...] = tuple(params) if params else ()
        with db_conn(logger=self.logger) as conn:
            with get_dict_cursor(conn) as cur:
                safe_execute_dict(cur, sql, sql_params)
                return cur.fetchone()

    def _fetch_all(
        self,
        sql: str,
        params: Sequence[Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Exécute un SELECT et retourne toutes les lignes.
        """
        if params is None:
            params = ()

        sql_params: tuple[Any, ...] = tuple(params) if params else ()
        with db_conn(logger=self.logger) as conn:
            with get_dict_cursor(conn) as cur:
                safe_execute_dict(cur, sql, sql_params)
                return list(cur.fetchall())

    # -------------------------------------------------------------
    # 🔍 Vérifie si une vidéo existe déjà
    # -------------------------------------------------------------
    def video_exists(self, uid: str) -> bool:
        try:
            row = self._fetch_one(
                "SELECT COUNT(*) AS count FROM videos WHERE uid=%s",
                (uid,),
            )
            exists = bool(row and row["count"] > 0)
            return exists
        except CutMindError as err:
            raise err.with_context(get_step_ctx({"uid": uid})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo video_exists.",
                code=ErrCode.DB,
                ctx=get_step_ctx({"uid": uid}),
            ) from exc

    def video_exists_by_video_path(self, video_path: str) -> int | None:
        try:
            row = self._fetch_one(
                "SELECT id FROM videos WHERE video_path=%s",
                (video_path,),
            )
            return row["id"] if row else None
        except CutMindError as err:
            raise err.with_context(get_step_ctx({"video_path": video_path})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo video_exists_by_video_path.",
                code=ErrCode.DB,
                ctx=get_step_ctx({"video_path": video_path}),
            ) from exc

    # -------------------------------------------------------------
    # 📥 Insertion vidéo + segments
    # -------------------------------------------------------------

    def insert_video_with_segments(self, video: Video) -> int:
        """
        Insère une vidéo et ses segments associés.
        """
        video_id: int | None = None
        try:
            with db_conn(logger=self.logger) as conn:
                with get_dict_cursor(conn) as cur:
                    # --- Vidéo ---
                    safe_execute_dict(
                        cur,
                        """
                        INSERT INTO videos (
                            uid, name, video_path, duration, fps, nb_frames, resolution, codec,
                            bitrate, filesize_mb, has_audio, audio_codec, sample_rate, channels,
                            audio_duration, status, origin
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            video.uid,
                            video.name,
                            video.video_path,
                            video.duration,
                            video.fps,
                            video.nb_frames,
                            video.resolution,
                            video.codec,
                            video.bitrate,
                            video.filesize_mb,
                            video.has_audio,
                            video.audio_codec,
                            video.sample_rate,
                            video.channels,
                            video.audio_duration,
                            video.status,
                            video.origin,
                        ),
                    )
                    video_id = cur.lastrowid

                    if not video_id:
                        raise CutMindError(
                            "❌ Erreur Repo insert_video_with_segments : ID non retourné.",
                            code=ErrCode.DB,
                            ctx=get_step_ctx({"video_id": video_id}),
                        )

                    # --- Segments ---
                    for seg in video.segments:
                        seg.video_id = video_id
                        seg_id = self._insert_segment(seg, cur)
                        if seg.keywords:
                            self.insert_keywords_for_segment(cur, seg_id, seg.keywords)

                    conn.commit()
                    return video_id
        except CutMindError as err:
            raise err.with_context(get_step_ctx({"video_id": video_id})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo insert_video_with_segments.",
                code=ErrCode.DB,
                ctx=get_step_ctx({"video_id": video_id}),
            ) from exc

    # -------------------------------------------------------------
    # 🧩 Insertion d’un segment (interne)
    # -------------------------------------------------------------
    def _insert_segment(
        self,
        seg: Segment,
        cur: DictCursorProtocol | None = None,
    ) -> int:
        # --- Mode autonome : on ouvre la connexion ---
        try:
            if cur is None:
                with db_conn(logger=self.logger) as conn:
                    with get_dict_cursor(conn) as cur2:
                        seg_id = self._insert_segment(seg, cur=cur2)
                        conn.commit()
                        return seg_id

            # --- Mode manuel : on utilise le cursor fourni ---
            assert cur is not None
            safe_execute_dict(
                cur,
                """
                INSERT INTO segments (
                    uid, video_id, start, end, duration, status, pipeline_target,
                    confidence, description, fps, nb_frames, resolution, codec,
                    bitrate, filesize_mb, has_audio, audio_codec, sample_rate,
                    channels, audio_duration, filename_predicted, output_path,
                    source_flow, processed_by, ai_model
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    seg.uid,
                    seg.video_id,
                    seg.start,
                    seg.end,
                    seg.duration,
                    seg.status,
                    seg.pipeline_target,
                    seg.confidence,
                    seg.description,
                    seg.fps,
                    seg.nb_frames,
                    seg.resolution,
                    seg.codec,
                    seg.bitrate,
                    seg.filesize_mb,
                    seg.has_audio,
                    seg.audio_codec,
                    seg.sample_rate,
                    seg.channels,
                    seg.audio_duration,
                    seg.filename_predicted,
                    seg.output_path,
                    seg.source_flow,
                    seg.processed_by,
                    seg.ai_model,
                ),
            )
            if not cur.lastrowid:
                raise CutMindError(
                    "❌ Erreur Repo _insert_segment : ID non retourné.",
                    code=ErrCode.DB,
                    ctx=get_step_ctx({"segment_id": seg.id}),
                )
            seg_id = cur.lastrowid
            if not seg_id:
                raise CutMindError(
                    "❌ Erreur Repo _insert_segment : ID non retourné.",
                    code=ErrCode.DB,
                    ctx=get_step_ctx({"segment_id": seg.id}),
                )
            return seg_id
        except CutMindError as err:
            raise err.with_context(get_step_ctx({"segment_id": seg.id})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo _insert_segment.",
                code=ErrCode.DB,
                ctx=get_step_ctx({"segment_id": seg.id}),
            ) from exc

    # -------------------------------------------------------------
    # 🔗 Insertion des mots-clés liés à un segment
    # -------------------------------------------------------------
    def insert_keywords_for_segment(
        self,
        cur: DictCursorProtocol,
        segment_id: int,
        keywords: list[str],
    ) -> None:
        """
        Insère les mots-clés d’un segment (en évitant les doublons).
        """
        try:
            # 🔥 DELETE UNE SEULE FOIS
            safe_execute_dict(
                cur,
                "DELETE FROM segment_keywords WHERE segment_id=%s",
                (segment_id,),
            )

            for kw in keywords:
                kw_clean = kw.strip().lower()
                if not kw_clean:
                    continue

                safe_execute_dict(
                    cur,
                    "SELECT id FROM keywords WHERE keyword=%s",
                    (kw_clean,),
                )
                row = cur.fetchone()

                if row:
                    kw_id = row["id"]
                else:
                    safe_execute_dict(
                        cur,
                        "INSERT INTO keywords (keyword) VALUES (%s)",
                        (kw_clean,),
                    )
                    kw_id = cur.lastrowid

                safe_execute_dict(
                    cur,
                    """
                    INSERT INTO segment_keywords (segment_id, keyword_id)
                    VALUES (%s, %s)
                    """,
                    (segment_id, kw_id),
                )

        except CutMindError as err:
            raise err.with_context(get_step_ctx({"segment_id": segment_id})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo insert_keywords_for_segment.",
                code=ErrCode.DB,
                ctx=get_step_ctx({"segment_id": segment_id}),
            ) from exc

    def insert_keywords_standalone(self, segment_id: int, keywords: list[str]) -> None:
        try:
            with db_conn(logger=self.logger) as conn:
                with get_dict_cursor(conn) as cur:
                    self.insert_keywords_for_segment(cur, segment_id, keywords)
                conn.commit()
        except CutMindError as err:
            raise err.with_context(get_step_ctx({"segment_id": segment_id})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo insert_keywords_standalone.",
                code=ErrCode.DB,
                ctx=get_step_ctx({"segment_id": segment_id}),
            ) from exc

    def replace_segment_frame_hashes(
        self,
        segment_id: int,
        hashes: list[SegmentFrameHash],
    ) -> None:
        """
        Supprime puis insère les hashes perceptuels d'un segment.

        Opération idempotente (safe pour re-run IA).
        """
        try:
            with db_conn(logger=self.logger) as conn:
                with get_dict_cursor(conn) as cur:
                    # 1️⃣ Delete existant
                    safe_execute_dict(
                        cur,
                        """
                        DELETE FROM segment_frame_hash
                        WHERE segment_id = %s
                        """,
                        (segment_id,),
                    )

                    # 2️⃣ Insert nouveau
                    if hashes:
                        values = [h.to_sql_values() for h in hashes]

                        safe_execute_dict(
                            cur,
                            """
                            INSERT INTO segment_frame_hash (
                                segment_id,
                                frame_index,
                                hash_type,
                                hash_value
                            ) VALUES (%s, %s, %s, %s)
                            """,
                            values,
                            many=True,  # ⬅️ important
                        )

                conn.commit()

        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo replace_segment_frame_hashes",
                code=ErrCode.DB,
                ctx=get_step_ctx({"segment_id": segment_id}),
            ) from exc

    def insert_processing_history(self, history: ProcessingHistory) -> int:
        """
        Insère une entrée dans la table processing_history et retourne l'ID.
        """
        try:
            with db_conn(logger=self.logger) as conn:
                with get_dict_cursor(conn) as cur:
                    safe_execute_dict(
                        cur,
                        """
                        INSERT INTO processing_history (
                            video_id,
                            segment_id,
                            video_name,
                            segment_uid,
                            action,
                            status,
                            message,
                            started_at,
                            ended_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        history.to_sql_values(),
                    )

                    history.id = cur.lastrowid

                    if not history.id:
                        raise CutMindError(
                            "❌ Erreur Repo insert_processing_history : ID non retourné.",
                            code=ErrCode.DB,
                            ctx=get_step_ctx({"action": history.action}),
                        )

                conn.commit()
                return history.id  # ✅ retourne l'ID inséré

        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo insert_processing_history",
                code=ErrCode.DB,
                ctx=get_step_ctx({"action": history.action}),
            ) from exc

    def update_processing_history(self, history: ProcessingHistory) -> None:
        """
        Met à jour le statut, le message et la date de fin d'une entrée processing_history.
        """
        if history.id is None:
            raise CutMindError(
                "❌ Impossible de mettre à jour une entrée sans ID.",
                code=ErrCode.DB,
                ctx=get_step_ctx(
                    {
                        "action": history.action,
                        "video_id": history.video_id,
                        "segment_id": history.segment_id,
                    }
                ),
            )

        try:
            with db_conn(logger=self.logger) as conn:
                with get_dict_cursor(conn) as cur:
                    safe_execute_dict(
                        cur,
                        """
                        UPDATE processing_history
                        SET status = %s,
                            message = %s,
                            ended_at = %s
                        WHERE id = %s
                        """,
                        (
                            history.status,
                            history.message,
                            history.ended_at.strftime("%Y-%m-%d %H:%M:%S"),
                            history.id,
                        ),
                    )
                conn.commit()
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur lors de la mise à jour processing_history",
                code=ErrCode.DB,
                ctx=get_step_ctx({"id": history.id, "action": history.action}),
            ) from exc

    # -------------------------------------------------------------
    # 🔎 Récupération d’une vidéo complète (segments + keywords)
    # -------------------------------------------------------------
    def get_video_with_segments(
        self,
        video_uid: str | None = None,
        video_id: int | None = None,
    ) -> Video | None:
        """
        Retourne un objet Video complet (avec ses segments et mots-clés).

        Peut recevoir soit video_uid, soit video_id.
        """
        ctx_base: dict[str, Any] = {}
        if video_id is not None:
            ctx_base["video.id"] = video_id
        if video_uid is not None:
            ctx_base["video.uid"] = video_uid

        try:
            if video_id is None and video_uid is None:
                raise CutMindError(
                    "❌ Erreur Repo get_video_with_segments : video_uid ou video_id doit être fourni.",
                    code=ErrCode.DB,
                    ctx=get_step_ctx(ctx_base),
                )

            with db_conn(logger=self.logger) as conn:
                with get_dict_cursor(conn) as cur:
                    # --- Identifier la ligne vidéo ---
                    if video_id is not None:
                        safe_execute_dict(cur, "SELECT * FROM videos WHERE id=%s", (video_id,))
                    else:
                        safe_execute_dict(cur, "SELECT * FROM videos WHERE uid=%s", (video_uid,))

                    video_row = cur.fetchone()
                    if not video_row:
                        return None

                    video = Video.from_row(video_row)
                    video.id = video_row["id"]

                    # --- Segments ---
                    safe_execute_dict(cur, "SELECT * FROM segments WHERE video_id=%s", (video.id,))
                    seg_rows = cur.fetchall()

                    for seg_row in seg_rows:
                        seg = Segment.from_row(seg_row)
                        seg.id = seg_row["id"]

                        if seg.id:
                            seg.keywords = self.get_keywords_for_segment(cur, seg.id)

                        video.segments.append(seg)

                    return video
        except CutMindError as err:
            raise err.with_context(get_step_ctx(ctx_base)) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo get_video_with_segments.",
                code=ErrCode.DB,
                ctx=get_step_ctx(ctx_base),
            ) from exc

    def get_videos_by_status(self, status: str) -> list[Video]:
        """
        Retourne toutes les vidéos (avec leurs segments et mots-clés) correspondant à un statut donné.
        """
        try:
            videos: list[Video] = []
            with db_conn(logger=self.logger) as conn:
                with get_dict_cursor(conn) as cur:
                    safe_execute_dict(cur, "SELECT * FROM videos WHERE status=%s", (status,))
                    video_rows = cur.fetchall()

                    for video_row in video_rows:
                        video = Video.from_row(video_row)
                        video.id = video_row["id"]

                        # --- Segments associés ---
                        safe_execute_dict(cur, "SELECT * FROM segments WHERE video_id=%s", (video.id,))
                        seg_rows = cur.fetchall()
                        for seg_row in seg_rows:
                            seg = Segment.from_row(seg_row)
                            seg.id = seg_row["id"]
                            if not seg.id:
                                continue
                            seg.keywords = self.get_keywords_for_segment(cur, seg.id)
                            video.segments.append(seg)

                        videos.append(video)

            return videos
        except CutMindError as err:
            raise err.with_context(get_step_ctx({"status": status})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo get_videos_by_status.",
                code=ErrCode.DB,
                ctx=get_step_ctx({"status": status}),
            ) from exc

    def get_video_id_from_segment_id(self, segment_id: int) -> int | None:
        """
        Retourne video_id à partir d'un id de segment.
        """
        try:
            row = self._fetch_one(
                "SELECT video_id FROM segments WHERE id=%s",
                (segment_id,),
            )
            return row["video_id"] if row else None
        except CutMindError as err:
            raise err.with_context(get_step_ctx({"segment_id": segment_id})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo get_video_id_from_segment_id.",
                code=ErrCode.DB,
                ctx=get_step_ctx({"segment_id": segment_id}),
            ) from exc

    def get_segments_by_status(self, status: str) -> list[Segment]:
        """
        Retourne tous les segments d’un statut donné.
        """
        try:
            rows = self._fetch_all(
                "SELECT * FROM segments WHERE status=%s",
                (status,),
            )
            return [Segment.from_row(row) for row in rows]
        except CutMindError as err:
            raise err.with_context(get_step_ctx({"status": status})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo get_segments_by_status.",
                code=ErrCode.DB,
                ctx=get_step_ctx({"status": status}),
            ) from exc

    def get_segments_pending_review(self) -> list[Segment]:
        """
        Retourne tous les segments en attente de validation manuelle.
        """
        statuses = ("manual_review", "pending_check", "manual_review_pending")
        try:
            placeholders = ",".join(["%s"] * len(statuses))
            query = f"SELECT * FROM segments WHERE status IN ({placeholders})"
            rows = self._fetch_all(query, statuses)
            return [Segment.from_row(row) for row in rows]
        except CutMindError as err:
            raise err.with_context(get_step_ctx()) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo get_segments_pending_review.",
                code=ErrCode.DB,
                ctx=get_step_ctx(),
            ) from exc

    def get_segments_by_ids(self, segment_ids: list[int]) -> list[Segment]:
        """
        Retourne les segments correspondant exactement aux IDs fournis.
        """
        if not segment_ids:
            return []

        try:
            placeholders = ",".join(["%s"] * len(segment_ids))
            query = f"SELECT * FROM segments WHERE id IN ({placeholders})"

            rows = self._fetch_all(query, tuple(segment_ids))
            return [Segment.from_row(row) for row in rows]

        except CutMindError as err:
            raise err.with_context(get_step_ctx({"segment_ids": segment_ids})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo get_segments_by_ids.",
                code=ErrCode.DB,
                ctx=get_step_ctx({"segment_ids": segment_ids}),
            ) from exc

    def get_segment_by_id(self, segment_id: int) -> Segment | None:
        query = "SELECT * FROM segments WHERE id = %s LIMIT 1"
        try:
            row = self._fetch_one(query, (segment_id,))
            if not row:
                return None
            return Segment.from_row(row)
        except CutMindError as err:
            raise err.with_context(get_step_ctx({"segment_id": segment_id})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo get_segment_by_id.",
                code=ErrCode.DB,
                ctx=get_step_ctx({"segment_id": segment_id}),
            ) from exc

    def get_segment_by_uid(self, uid: str) -> Segment | None:
        """
        Retourne un segment spécifique par son UID.
        """
        try:
            row = self._fetch_one(
                "SELECT * FROM segments WHERE uid=%s",
                (uid,),
            )
            if not row:
                return None
            return Segment.from_row(row)
        except CutMindError as err:
            raise err.with_context(get_step_ctx({"uid": uid})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo get_segments_by_uid.",
                code=ErrCode.DB,
                ctx=get_step_ctx({"uid": uid}),
            ) from exc

    def get_segments_by_category(self, category: str | None, expected_segment_statuses: list[str]) -> list[Segment]:
        """
        Récupère tous les segments 'enhanced' d'une catégorie donnée (ou NULL si category=None).
        """
        try:
            params: tuple[Any, ...]
            if category is None:
                query = """
                    SELECT s.*
                    FROM segments s
                    WHERE s.status IN %s
                    AND s.category IS NULL
                    ORDER BY s.created_at DESC
                """
                params = (tuple(expected_segment_statuses),)
            else:
                query = """
                    SELECT s.*
                    FROM segments s
                    WHERE s.status IN %s
                    AND s.category = %s
                    ORDER BY s.created_at DESC
                """
                params = (tuple(expected_segment_statuses), category)

            rows = self._fetch_all(query, params if params else None)
            return [Segment.from_row(row) for row in rows]

        except CutMindError as err:
            raise err.with_context(get_step_ctx({"category": category})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo get_segments_by_category.",
                code=ErrCode.DB,
                ctx=get_step_ctx({"category": category}),
            ) from exc

    # -------------------------------------------------------------
    # 🏷️ Récupération des mots-clés d’un segment
    # -------------------------------------------------------------
    def get_keywords_for_segment(self, cur: DictCursorProtocol, segment_id: int) -> list[str]:
        try:
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
        except CutMindError as err:
            raise err.with_context(get_step_ctx({"segment_id": segment_id})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo get_keywords_for_segment.",
                code=ErrCode.DB,
                ctx=get_step_ctx({"segment_id": segment_id}),
            ) from exc

    def get_nonstandard_videos(self, limit_videos: int = 10) -> list[str]:
        """
        Retourne les UID de vidéos 'validated' contenant au moins un segment dont la résolution ou les FPS sont
        inférieurs aux standards (1920x1080, 60fps).
        """
        try:
            rows = self._fetch_all(
                """
                SELECT DISTINCT v.uid
                FROM videos v
                JOIN segments s ON v.id = s.video_id
                WHERE
                    v.status = %s
                    AND s.status = %s
                    AND (
                        CAST(SUBSTRING_INDEX(s.resolution, 'x', 1) AS UNSIGNED) < 1920
                        OR CAST(SUBSTRING_INDEX(s.resolution, 'x', -1) AS UNSIGNED) < 1080
                        OR s.fps IS NULL
                        OR s.fps <> 60.0
                    )
                ORDER BY RAND()
                LIMIT %s
                """,
                (
                    OrchestratorStatus.VIDEO_READY_FOR_ENHANCEMENT,
                    OrchestratorStatus.VIDEO_READY_FOR_ENHANCEMENT,
                    limit_videos,
                ),
            )
            return [row["uid"] for row in rows if "uid" in row]
        except CutMindError as err:
            raise err.with_context(get_step_ctx()) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo get_non_standard_videos.",
                code=ErrCode.DB,
                ctx=get_step_ctx(),
            ) from exc

    def get_standard_videos(self, limit_videos: int = 10) -> list[str]:
        """
        Retourne les UID de vidéos 'validated' dont tous les segments sont déjà en 1080p 60fps.
        """
        try:
            rows = self._fetch_all(
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
            )
            return [row["uid"] for row in rows if "uid" in row]
        except CutMindError as err:
            raise err.with_context(get_step_ctx()) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo get_standard_videos.",
                code=ErrCode.DB,
                ctx=get_step_ctx(),
            ) from exc

    def get_active_videos(self) -> list[Video]:
        """
        Retourne les vidéos pouvant avancer automatiquement :

        - au moins un segment
        - aucun segment en attente de validation humaine
        """
        try:
            query = """
                SELECT v.*
                FROM videos v
                WHERE EXISTS (
                    SELECT 1
                    FROM segments s
                    WHERE s.video_id = v.id
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM segments s
                    WHERE s.video_id = v.id
                    AND s.pipeline_target IN ('VALIDATION', 'VALIDATION_CUT')
                )
            """
            rows = self._fetch_all(query)
            return [Video.from_row(row) for row in rows]

        except CutMindError as err:
            raise err.with_context(get_step_ctx()) from err

        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo get_active_videos.",
                code=ErrCode.DB,
                ctx=get_step_ctx(),
            ) from exc

    def get_segments_by_video_status(self, video_status: str) -> list[dict[str, Any]]:
        """
        Retourne la liste des segments (id + status) pour les vidéos ayant un statut donné.
        """
        try:
            query = """
                SELECT s.id AS segment_id, s.status AS segment_status
                FROM videos v
                JOIN segments s ON s.video_id = v.id
                WHERE v.status = %s
            """
            return self._fetch_all(query, (video_status,))
        except CutMindError as err:
            raise err.with_context(get_step_ctx({"video_status": video_status})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo get_segments_by_video_status.",
                code=ErrCode.DB,
                ctx=get_step_ctx({"video_status": video_status}),
            ) from exc

    def get_segment_status_counts_by_video_status(self, video_status: str) -> dict[str, int]:
        """
        Retourne un dict {segment_status: count} pour un statut vidéo donné.
        """
        try:
            query = """
                SELECT s.status, COUNT(*) AS cnt
                FROM videos v
                JOIN segments s ON s.video_id = v.id
                WHERE v.status = %s
                GROUP BY s.status
            """
            rows = self._fetch_all(query, (video_status,))
            return {row["status"]: row["cnt"] for row in rows}
        except CutMindError as err:
            raise err.with_context(get_step_ctx({"video_status": video_status})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo get_segment_status_counts_by_video_status.",
                code=ErrCode.DB,
                ctx=get_step_ctx({"video_status": video_status}),
            ) from exc

    def get_segments_status_mismatch(
        self, video_status: str, expected_segment_statuses: list[str]
    ) -> list[dict[str, Any]]:
        """
        Retourne les segments dont le statut est incohérent avec celui de leur vidéo.

        Ex: vidéo.status = 'validated' mais segment.status = 'pending_check'
        """
        try:
            query = """
                SELECT v.id AS video_id, v.filename, s.id AS segment_id, s.status AS segment_status
                FROM videos v
                JOIN segments s ON s.video_id = v.id
                WHERE v.status = %s
                AND s.status NOT IN %s
            """
            rows = self._fetch_all(query, (video_status, tuple(expected_segment_statuses)))
            return rows
        except CutMindError as err:
            raise err.with_context(get_step_ctx({"video_status": video_status})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo get_segments_status_mismatch.",
                code=ErrCode.DB,
                ctx=get_step_ctx({"video_status": video_status}),
            ) from exc

    # -------------------------------------------------------------
    # 🔄 Mise à jour d’un segment
    # -------------------------------------------------------------
    def update_segment_validation(self, seg: Segment, conn: Connection | None = None) -> None:
        """
        Mise à jour suite à validation automatique ou manuelle.
        """
        try:
            self._exec_sql(
                """
                UPDATE segments
                SET status=%s,
                    pipeline_target=%s,
                    source_flow=%s,
                    confidence=%s,
                    description=%s,
                    filename_predicted=%s,
                    output_path=%s,
                    category=%s,
                    ai_model=%s,
                    tags=%s,
                    quality_score=%s,
                    rating=%s,
                    last_updated=NOW()
                WHERE uid=%s
                """,
                (
                    seg.status,
                    seg.pipeline_target,
                    seg.source_flow,
                    seg.confidence,
                    seg.description,
                    seg.filename_predicted,
                    seg.output_path,
                    seg.category,
                    seg.ai_model,
                    to_db_json(seg.tags),
                    seg.quality_score,
                    seg.rating,
                    seg.uid,
                ),
                conn=conn,
            )
        except CutMindError as err:
            raise err.with_context(get_step_ctx({"seg.id": seg.id})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo update_segment_validation.",
                code=ErrCode.DB,
                ctx=get_step_ctx({"seg.id": seg.id}),
            ) from exc

    def update_segment_postprocess(self, seg: ProcessedSegment, conn: Connection | None = None) -> None:
        """
        Mise à jour après traitement ComfyUI.
        """
        try:
            self._exec_sql(
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
                    nb_frames=%s,
                    last_updated=NOW()
                WHERE id=%s
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
                    to_db_json(seg.tags),
                    seg.nb_frames,
                    seg.id,
                ),
                conn=conn,
            )
        except CutMindError as err:
            raise err.with_context(get_step_ctx({"seg.id": seg.id})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo update_segment_postprocess.",
                code=ErrCode.DB,
                ctx=get_step_ctx({"seg.id": seg.id}),
            ) from exc

    def update_segment_from_metadata(
        self,
        segment_id: int,
        metadata: VideoPrepared,
        conn: Connection | None = None,
    ) -> None:
        """
        Met à jour les métadonnées techniques d'un segment à partir d'un VideoPrepared.

        Utilise _exec_sql() pour respecter l'architecture Repository.
        """

        # mapping: attribut VideoPrepared → colonne SQL
        FIELD_MAP: dict[str, str] = {
            "resolution": "resolution",
            "fps": "fps",
            "duration": "duration",
            "codec": "codec",
            "bitrate": "bitrate",
            "filesize_mb": "filesize_mb",
            "nb_frames": "nb_frames",
            "has_audio": "has_audio",
            "audio_codec": "audio_codec",
            "sample_rate": "sample_rate",
            "channels": "channels",
            "audio_duration": "audio_duration",
        }

        try:
            # auto-gestion de connexion
            if conn is None:
                with db_conn(logger=self.logger) as conn:
                    self.update_segment_from_metadata(segment_id, metadata, conn)
                    conn.commit()
                return

            # SQL dynamique
            sql_parts = []
            values: list[Any] = []

            for meta_attr, col in FIELD_MAP.items():
                values.append(getattr(metadata, meta_attr, None))
                sql_parts.append(f"{col}=%s")

            values.append(segment_id)

            sql = f"""
                UPDATE segments
                SET {", ".join(sql_parts)}, last_updated=NOW()
                WHERE id=%s
            """

            # exécution via le helper générique
            self._exec_sql(sql, tuple(values), conn)

        except CutMindError as err:
            raise err.with_context(get_step_ctx({"segment.id": segment_id})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo update_segment_from_metadata.",
                code=ErrCode.DB,
                ctx=get_step_ctx({"segment.id": segment_id}),
            ) from exc

    def update_segment_from_csv(self, segment: Segment, new_data: dict[str, Any], diffs: list[str]) -> None:
        """
        Compare et met à jour les champs d’un segment depuis CSV.
        """
        try:
            with db_conn(logger=self.logger) as conn:
                with get_dict_cursor(conn) as cur:
                    safe_execute_dict(
                        cur,
                        """
                        UPDATE segments
                        SET description=%s, confidence=%s, status=%s, pipeline_target=%s, category=%s,
                            source_flow='manual_csv', last_updated=NOW()
                        WHERE id=%s
                        """,
                        (
                            new_data["description"],
                            new_data["confidence"],
                            new_data["status"],
                            new_data["pipeline_target"],
                            new_data["category"],
                            segment.id,
                        ),
                    )
                    conn.commit()

            if "keywords" in diffs:
                with db_conn(logger=self.logger) as conn:
                    with get_dict_cursor(conn) as cur:
                        safe_execute_dict(cur, "DELETE FROM segment_keywords WHERE segment_id=%s", (segment.id,))
                        conn.commit()
                for kw in new_data["keywords"]:
                    with db_conn(logger=self.logger) as conn:
                        with get_dict_cursor(conn) as cur:
                            safe_execute_dict(cur, "SELECT id FROM keywords WHERE keyword=%s", (kw,))
                            row_kw = cur.fetchone()
                    if not row_kw:
                        with db_conn(logger=self.logger) as conn:
                            with get_dict_cursor(conn) as cur:
                                safe_execute_dict(cur, "INSERT INTO keywords (keyword) VALUES (%s)", (kw,))
                                kw_id = cur.lastrowid
                    else:
                        kw_id = row_kw["id"]

                    with db_conn(logger=self.logger) as conn:
                        with get_dict_cursor(conn) as cur:
                            safe_execute_dict(
                                cur,
                                "INSERT INTO segment_keywords (segment_id, keyword_id) VALUES (%s, %s)",
                                (segment.id, kw_id),
                            )
                            conn.commit()
        except CutMindError as err:
            raise err.with_context(get_step_ctx({"segment_id": segment.id})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur de la modif via CSV.",
                code=ErrCode.UNEXPECTED,
                ctx=get_step_ctx({"segment_id": segment.id}),
            ) from exc

    # -------------------------------------------------------------
    # 🔄 Mise à jour d’une vidéo
    # -------------------------------------------------------------
    def update_video(self, video: Video, conn: Connection | None = None) -> None:
        """
        Met à jour le statut ou autres champs d’une vidéo.
        """
        try:
            self._exec_sql(
                """
                UPDATE videos
                SET status=%s,
                    video_path=%s,
                    tags=%s,
                    last_updated=NOW()
                WHERE uid=%s
                """,
                (
                    video.status,
                    video.video_path,
                    to_db_json(video.tags),
                    video.uid,
                ),
                conn=conn,
            )
        except CutMindError as err:
            raise err.with_context(get_step_ctx({"video.name": video.name})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo update_video.",
                code=ErrCode.DB,
                ctx=get_step_ctx({"video.name": video.name}),
            ) from exc

    # ------------------------------------------------------------------
    # 🔹 SUPPRESSION
    # ------------------------------------------------------------------
    def delete_segment_by_uid(self, seg_uid: str) -> bool:
        """
        Supprime un segment spécifique.
        """
        try:
            self._exec_sql(
                "DELETE FROM segments WHERE uid=%s",
                (seg_uid,),
            )
            return True
        except CutMindError as err:
            raise err.with_context(get_step_ctx({"seg_uid": seg_uid})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo delete_segment_by_uid.",
                code=ErrCode.DB,
                ctx=get_step_ctx({"seg_uid": seg_uid}),
            ) from exc

    def delete_segment(self, seg_id: int) -> None:
        """
        Supprime un segment et ses mots-clés.
        """
        try:
            with db_conn(logger=self.logger) as conn:
                with get_dict_cursor(conn) as cur:
                    safe_execute_dict(cur, "DELETE FROM segments WHERE id=%s", (seg_id,))
                    safe_execute_dict(cur, "DELETE FROM segment_keywords WHERE segment_id=%s", (seg_id,))
                    conn.commit()
        except CutMindError as err:
            raise err.with_context(get_step_ctx({"seg_id": seg_id})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo delete_segment.",
                code=ErrCode.DB,
                ctx=get_step_ctx({"seg_id": seg_id}),
            ) from exc

    # ------------------------------------------------------------------
    # 🧱 CONTEXTE TRANSACTIONNEL (global)
    # ------------------------------------------------------------------
    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        """
        Contexte transactionnel global basé sur db_conn(logger=self.logger). Permet d'exécuter plusieurs opérations du
        repository dans une seule et même transaction SQL.

        Exemple :
            with repo.transaction() as conn:
                repo.update_segment_validation(seg, conn)
                repo.update_video(video, conn)
        """

        with db_conn(logger=self.logger) as conn:
            try:
                yield conn
            except CutMindError as err:
                raise err.with_context(get_step_ctx()) from err
            except Exception as exc:
                raise CutMindError(
                    "❌ Rollback transaction SQL.",
                    code=ErrCode.DB,
                    ctx=get_step_ctx(),
                ) from exc
