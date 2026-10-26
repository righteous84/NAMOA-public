from pathlib import Path
import os

from app.preview.artifacts import (
    ARTIFACT_PREFIX,
    DEFAULT_PREVIEW_DIR,
)
from app.services.exclusion_service import get_excluded_paths
from app.utils.logger import logger


VIDEO_EXTENSIONS = {
    ".mkv",
    ".mp4",
    ".avi",
    ".mov",
    ".wmv",
    ".ts",
}


def is_video_file(file_path: Path) -> bool:
    return file_path.suffix.lower() in VIDEO_EXTENSIONS


def scan_directory(root_path: str):
    root = Path(root_path)

    if not root.exists():
        logger.error(
            f"Path does not exist: {root_path}"
        )
        return []

    excluded_paths = get_excluded_paths()

    try:
        preview_anchor = str(DEFAULT_PREVIEW_DIR.resolve())
    except Exception:
        preview_anchor = ""

    found_files = []

    for dirpath, _, filenames in os.walk(root):

        for filename in filenames:

            file_path = Path(dirpath) / filename
            full_path = str(file_path)

            # -------------------------
            # Exclusions
            # -------------------------

            if any(
                full_path.startswith(ex)
                for ex in excluded_paths
            ):
                continue

            # Transient optimisation preview artifacts are
            # application-owned temporaries, never library media,
            # even if a scan root ever covers their directory.
            if preview_anchor and (
                full_path == preview_anchor
                or full_path.startswith(preview_anchor + os.sep)
            ):
                continue

            if filename.startswith(ARTIFACT_PREFIX):
                continue

            # -------------------------
            # Video filter
            # -------------------------

            if not is_video_file(file_path):
                continue

            try:

                stat = file_path.stat()

                size_bytes = stat.st_size

                file_mtime_ns = stat.st_mtime_ns

                filesystem_device = stat.st_dev

                filesystem_inode = stat.st_ino

                found_files.append(
                    {
                        "path": full_path,

                        "name": filename,

                        "size_bytes": size_bytes,

                        "file_mtime_ns":
                            file_mtime_ns,

                        "extension":
                            file_path.suffix.lower(),

                        "filesystem_device":
                            filesystem_device,

                        "filesystem_inode":
                            filesystem_inode,
                    }
                )

            except Exception as e:

                logger.warning(
                    f"File stat error: "
                    f"{full_path} | {e}"
                )

    logger.info(
        f"Found {len(found_files)} video files"
    )

    return found_files
