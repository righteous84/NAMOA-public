"""
Lineage recording for executed media (Sprint 9).

After a controlled replacement, the resulting file must receive the
correct NEW filesystem observation through the EXISTING lineage
machinery (MediaRepository.sync_media, path-continuity identity).
This module builds the MediaContext from real post-replacement
filesystem facts plus the already-verified output characteristics and
records the observation.

Historical observations are never rewritten; sync_media appends.
"""

import os

from pathlib import Path

from app.models.media_context import MediaContext


def build_media_context(
    *,
    path,
    summary,
):
    """
    Build a pipeline-shaped MediaContext for an executed file from
    its filesystem facts and its verified probe summary.
    """

    stat = os.stat(path)

    name = os.path.basename(path)

    size_bytes = stat.st_size

    return MediaContext(
        path=path,
        name=name,
        extension=os.path.splitext(name)[1].lower(),
        container=(summary or {}).get("container", "mp4"),
        size_bytes=size_bytes,
        file_mtime_ns=stat.st_mtime_ns,
        size_mib=round(size_bytes / (1024 * 1024), 3),
        size_gib=round(size_bytes / (1024 ** 3), 6),
        duration=(summary or {}).get("duration"),
        bitrate=(summary or {}).get("bitrate"),
        width=(summary or {}).get("width"),
        height=(summary or {}).get("height"),
        video_codec=(summary or {}).get("video_codec"),
        audio_channels=(summary or {}).get("audio_channels"),
        raw_ffprobe=dict(summary or {}),
        raw_scanner={
            "path": path,
            "name": name,
            "size_bytes": size_bytes,
            "file_mtime_ns": stat.st_mtime_ns,
            "filesystem_device": stat.st_dev,
            "filesystem_inode": stat.st_ino,
            "extension": Path(path).suffix.lower(),
        },
    )


def record_execution_observation(
    media_repository,
    *,
    path,
    summary,
):
    """
    Record the new filesystem observation for an executed file via
    the existing canonical lineage mechanism. Returns
    (media_id, scan_status, observation_id).
    """

    context = build_media_context(
        path=path,
        summary=summary,
    )

    return media_repository.sync_media(context)


def find_existing_observation_id(
    media_repository,
    *,
    media_id,
    path,
):
    """
    Return the id of an existing observation of `path` whose
    filesystem fingerprint matches the live file, or None.

    Used by execution recovery to avoid appending a duplicate
    observation when the original recording already committed before
    an interruption. Delegates entirely to MediaRepository reads.
    """

    stat = os.stat(path)

    for observation in (
        media_repository.get_file_observations(media_id)
    ):

        if (
            observation.size_bytes == stat.st_size
            and observation.file_mtime_ns
            == stat.st_mtime_ns
        ):

            return observation.id

    return None
