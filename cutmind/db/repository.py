"""
CutMind Repository (v3.4)
=========================

Couche d’accès à la base de données MariaDB pour le projet CutMind.

- Gestion des vidéos et segments
- Insertion / lecture / mise à jour cohérente
- Basé sur db_conn() et safe_execute_dict() pour sécurité et logs
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from pymysql.connections import Connection

from comfyui_router.models_cr.processed_segment import ProcessedSegment
from cutmind.db.db_connection import db_conn, get_dict_cursor
from cutmind.db.db_utils import safe_execute_dict
from cutmind.models_cm.cursor_protocol import DictCursorProtocol
from cutmind.models_cm.db_models import Segment, Video
from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.services.video_preparation import VideoPrepared


# =====================================================================
# 🎯 Repository principal
# =====================================================================
class CutMindRepository:
    """Gestion centralisée des accès à la base de données CutMind."""

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
                with db_conn() as _conn:
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
        with db_conn() as conn:
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
        with db_conn() as conn:
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
        """Insère une vidéo et ses segments associés."""
        video_id: int | None = None
        try:
            with db_conn() as conn:
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
                with db_conn() as conn:
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
                    uid, video_id, start, end, duration, status,
                    confidence, description, fps, nb_frames, resolution, codec,
                    bitrate, filesize_mb, has_audio, audio_codec, sample_rate,
                    channels, audio_duration, filename_predicted, output_path,
                    source_flow, processed_by, ai_model
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
    def insert_keywords_for_segment(self, cur: DictCursorProtocol, segment_id: int, keywords: list[str]) -> None:
        """Insère les mots-clés d’un segment (en évitant les doublons)."""
        try:
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
            with db_conn() as conn:
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

            with db_conn() as conn:
                with get_dict_cursor(conn) as cur:
                    # --- Identifier la ligne vidéo ---
                    if video_id is not None:
                        safe_execute_dict(cur, "SELECT * FROM videos WHERE id=%s", (video_id,))
                    else:
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
        Retourne toutes les vidéos (avec leurs segments et mots-clés)
        correspondant à un statut donné.
        """
        try:
            videos: list[Video] = []
            with db_conn() as conn:
                with get_dict_cursor(conn) as cur:
                    safe_execute_dict(cur, "SELECT * FROM videos WHERE status=%s", (status,))
                    video_rows = cur.fetchall()

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
        """Retourne tous les segments d’un statut donné."""
        try:
            rows = self._fetch_all(
                "SELECT * FROM segments WHERE status=%s",
                (status,),
            )
            return [Segment(**{k: row[k] for k in row if k in Segment.__annotations__}) for row in rows]
        except CutMindError as err:
            raise err.with_context(get_step_ctx({"status": status})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo get_segments_by_status.",
                code=ErrCode.DB,
                ctx=get_step_ctx({"status": status}),
            ) from exc

    def get_segments_pending_review(self) -> list[Segment]:
        """Retourne tous les segments en attente de validation manuelle."""
        statuses = ("manual_review", "pending_check", "manual_review_pending")
        try:
            placeholders = ",".join(["%s"] * len(statuses))
            query = f"SELECT * FROM segments WHERE status IN ({placeholders})"
            rows = self._fetch_all(query, statuses)
            return [Segment(**{k: row[k] for k in row if k in Segment.__annotations__}) for row in rows]
        except CutMindError as err:
            raise err.with_context(get_step_ctx()) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo get_segments_pending_review.",
                code=ErrCode.DB,
                ctx=get_step_ctx(),
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
        """Retourne un segment spécifique par son UID."""
        try:
            row = self._fetch_one(
                "SELECT * FROM segments WHERE uid=%s",
                (uid,),
            )
            if not row:
                return None
            return Segment(**{k: row[k] for k in row if k in Segment.__annotations__})
        except CutMindError as err:
            raise err.with_context(get_step_ctx({"uid": uid})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo get_segments_by_uid.",
                code=ErrCode.DB,
                ctx=get_step_ctx({"uid": uid}),
            ) from exc

    def get_segments_by_category(self, category: str) -> list[Segment]:
        """
        Récupère tous les segments 'enhanced' d'une catégorie donnée.
        """
        try:
            rows = self._fetch_all(
                """
                SELECT s.*
                FROM segments s
                WHERE s.status = 'enhanced'
                AND s.category = %s
                ORDER BY s.created_at DESC
                """,
                (category,),
            )
            return [Segment.from_row(row) for row in rows]
        except CutMindError as err:
            raise err.with_context(get_step_ctx({"category": category})) from err
        except Exception as exc:
            raise CutMindError(
                "❌ Erreur Repo gget_segments_by_category.",
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
        Retourne les UID de vidéos 'validated' contenant au moins un segment
        dont la résolution ou les FPS sont inférieurs aux standards (1920x1080, 60fps).
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

    # -------------------------------------------------------------
    # 🔄 Mise à jour d’un segment
    # -------------------------------------------------------------
    def update_segment_validation(self, seg: Segment, conn: Connection | None = None) -> None:
        """Mise à jour suite à validation automatique ou manuelle."""
        try:
            self._exec_sql(
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
        """Mise à jour après traitement ComfyUI."""
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
                    seg.tags,
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
                with db_conn() as conn:
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

    # -------------------------------------------------------------
    # 🔄 Mise à jour d’une vidéo
    # -------------------------------------------------------------
    def update_video(self, video: Video, conn: Connection | None = None) -> None:
        """Met à jour le statut ou autres champs d’une vidéo."""
        try:
            self._exec_sql(
                """
                UPDATE videos
                SET status=%s,
                    video_path=%s,
                    last_updated=NOW()
                WHERE uid=%s
                """,
                (
                    video.status,
                    video.video_path,
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
        """Supprime un segment spécifique."""
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
        """Supprime un segment et ses mots-clés."""
        try:
            with db_conn() as conn:
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
                yield conn
            except CutMindError as err:
                raise err.with_context(get_step_ctx()) from err
            except Exception as exc:
                raise CutMindError(
                    "❌ Rollback transaction SQL.",
                    code=ErrCode.DB,
                    ctx=get_step_ctx(),
                ) from exc
