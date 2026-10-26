"""
Sprint 9 Execution Engine.

This package is the ONLY place in NAMOA that may construct or run
FFmpeg commands and perform controlled media replacement. External
interfaces (CLI/GUI/API) reach it exclusively through
ExecutionService (app/application), never directly.

Safety model:

- argument-list subprocess execution; shell interpolation is never
  used and no user-supplied command strings exist anywhere
- operation set is closed (v1: lossless remux to MP4)
- source path always comes from the authoritative lineage record,
  never from request input
- output is produced to a temporary file on the same filesystem as
  the source, verified, and only then swapped into place with atomic
  renames; the original bytes are preserved under a recorded backup
  path so rollback/recovery stays possible
"""
