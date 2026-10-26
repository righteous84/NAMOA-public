"""Quick Find application service (Phase 6).

A thin single-file workflow over the existing pipeline. It selects one
media path, runs the canonical analysis pipeline, and returns the
current-valid recommendation through the existing recommendation
authority. It is NOT a second intelligence system: it reuses scanner
observation, analysis, recommendation, approval, and execution
boundaries unchanged.

Identity semantics are conservative:

- an unknown path becomes a new lineage (never attached to an existing
  identity by filename alone)
- an already-known lineage is resolved by actual identity evidence
  through the existing observation/lineage machinery
"""

import os

from pathlib import Path


class QuickFindService:
    """
    Application-facing single-file analyse-and-recommend workflow.
    """

    def __init__(
        self,
        *,
        analysis_service,
        media_service,
        recommendation_service,
    ):

        self.analysis_service = analysis_service

        self.media_service = media_service

        self.recommendation_service = recommendation_service

    def find(
        self,
        path,
        *,
        database_path=None,
    ) -> dict:
        """
        Analyse ONE file and return its current-valid recommendation.

        Raises ValueError for invalid/unreadable/non-video input.
        Returns:

            {
                "path": str,
                "media_id": int | None,
                "lineage_id": int | None,
                "lineage_name": str | None,
                "candidate": OptimisationCandidate | None,
                "analysis_reported": bool
            }

        The candidate (when present) is the authoritative current-valid
        recommendation for that lineage; approval and execution flow
        through the existing boundaries unchanged.
        """

        resolved = str(path).strip()

        file_path = Path(resolved)

        if not file_path.exists():

            raise ValueError(
                f"path does not exist: {resolved}"
            )

        if not file_path.is_file():

            raise ValueError(
                f"path is not a file: {resolved}"
            )

        if file_path.suffix.lower() not in {
            ".mkv", ".mp4", ".avi", ".mov", ".wmv", ".ts",
        }:

            raise ValueError(
                f"not a supported video file: {resolved}"
            )

        try:

            stat = file_path.stat()

        except OSError as error:

            raise ValueError(
                f"cannot stat file: {resolved}"
            ) from error

        record = {
            "path": str(file_path),
            "name": file_path.name,
            "size_bytes": stat.st_size,
            "file_mtime_ns": stat.st_mtime_ns,
            "extension": file_path.suffix.lower(),
            "filesystem_device": stat.st_dev,
            "filesystem_inode": stat.st_ino,
        }

        enriched = self.analysis_service.analyze(
            [record],
            database_path=database_path,
        )

        # Resolve the lineage by actual identity evidence: the
        # pipeline records the new/continued observation; we look up
        # the ACTIVE lineage for the exact path (never by filename
        # alone).
        media_id = self._resolve_lineage_id(
            str(file_path),
            database_path,
        )

        candidate = None

        if media_id is not None:

            for item in (
                self.recommendation_service
                .get_current_queue()
            ):

                if item.media_id == media_id:

                    candidate = item

                    break

        lineage_name = file_path.name

        return {
            "path": str(file_path),
            "media_id": media_id,
            "lineage_id": media_id,
            "lineage_name": lineage_name,
            "candidate": candidate,
            "analysis_reported": bool(enriched),
        }

    def _resolve_lineage_id(self, path, database_path):
        """
        The active lineage whose current filesystem path equals the
        requested path. Path equality is the identity evidence the
        observation machinery already recorded; an unknown path
        simply resolves to None.
        """

        for lineage in self.media_service.get_active_lineages():

            if lineage.file_path == path:

                return lineage.id

        return None