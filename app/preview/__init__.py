"""Optimisation Preview subsystem (Phase 17).

Preview is a consumer of existing recommendation and transformation
authority. It introduces no new intelligence, no new currentness
system, no new execution queue, and no new operation model:

- recommendation contexts resolve through the existing queue,
  validity, and review authorities;
- transformations resolve through TransformationService and the
  closed operation registry;
- segments reuse the registered argv builders via
  ``app.execution.ffmpeg.build_preview_argv``;
- artifacts live in an application-owned directory with ownership
  markers and server-side lifecycle (never library media).
"""
