# check/check_enhanced_segments.py


# @with_child_logger
# def kw_generate(status: str = "enhanced", logger: LoggerProtocol | None = None) -> None:
#     logger = ensure_logger(logger, __name__)
#     logger.info("💫 Démarrage du check_secure_in_router.")
#     repo = CutMindRepository()
#     try:
#         videos = repo.get_videos_by_status(status)
#         modified_count = 0
#         logger.info(f"▶️ videos avec le statut {status} : {len(videos)}")
#         for video in videos:
#             logger.info("▶️ processing_router : %s", video.name)
#             for seg in video.segments:
#                 seg.description, seg.keywords = analyze_from_cutmind(seg, logger)

#                 seg.status = "validated"
#                 repo.update_segment_validation(seg)
#                 logger.info("✅ Segment mis à jour : %s", seg.uid)
#                 modified_count += 1

#             video.status = "validated"
#             repo.update_video(video)

#         logger.info("✔️ Vérification Secure in Router terminée. %d segments mis à jour.", modified_count)
#     except Exception as exc:
#         raise CutMindError(
#             "❌ Erreur inattendue lors de check_secure_in_router.",
#             code=ErrCode.UNEXPECTED,
#             ctx=get_step_ctx({"video": video.name, "segment_id": seg.id}),
#         ) from exc
