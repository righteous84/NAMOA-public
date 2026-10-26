"""Read-only filesystem browsing service (GUI/UX Phase 5).

Provides a directory-listing read for the Scan folder browser. This
is a read-only application capability: it never scans media, never
starts a scan, and never mutates the filesystem. The browser is
bounded to directories the NAMOA process can actually access.

Cross-platform: filesystem roots are resolved per platform
(POSIX '/' ; Windows drive roots). No '/mnt' assumption anywhere.
"""

import os
from pathlib import Path


def scan_file_record(path: str) -> dict:
    """
    Read-only scan record for one media file (path,
    name, extension, size, mtime, device, inode).
    Used by ephemeral What-If planning for files NAMOA
    has never seen. Stats only; persists nothing,
    mutates nothing. Raises ValueError with a
    human-readable message when the path is unusable.
    """

    from app.scanner.scanner import is_video_file

    raw = str(path or "").strip()

    if not raw:
        raise ValueError("a file path is required")

    if not os.path.exists(raw):
        raise ValueError(f"file not found: {raw}")

    if not os.path.isfile(raw) or os.path.islink(raw):
        raise ValueError(f"not a regular file: {raw}")

    if not is_video_file(Path(raw)):
        raise ValueError(
            f"not a supported media file: {raw}"
        )

    try:
        stat = os.stat(raw)
    except OSError as error:
        raise ValueError(
            f"cannot read file metadata: {error}"
        ) from error

    absolute = os.path.abspath(raw)

    return {
        "path": absolute,
        "name": os.path.basename(absolute),
        "extension": os.path.splitext(absolute)[1].lower(),
        "size_bytes": stat.st_size,
        "file_mtime_ns": stat.st_mtime_ns,
        "filesystem_device": str(stat.st_dev),
        "filesystem_inode": stat.st_ino,
    }


class FilesystemService:
    """
    Application-facing read for folder browsing.
    """

    def roots(self) -> list[dict]:
        """
        The platform's filesystem roots the NAMOA process can see.
        """

        entries = []

        if os.name == "nt":
            # Windows drive roots that actually exist.
            import string

            for letter in string.ascii_uppercase:
                candidate = Path(f"{letter}:\\")
                if candidate.exists():
                    entries.append(
                        {
                            "name": candidate.name or str(candidate),
                            "path": str(candidate),
                        }
                    )
            return entries

        # POSIX: a single root.
        root = Path(os.path.sep)
        return [
            {
                "name": root.name or str(root),
                "path": str(root),
            }
        ]

    def list_directories(self, path: str | None = None) -> dict:
        """
        List the accessible subdirectories of `path`, or the
        platform roots when path is absent/empty.

        Returns a dict suitable for presentation:

            {
                "current": str | None,
                "is_root": bool,
                "parent": str | None,
                "entries": [
                    {"name": ..., "path": ..., "is_dir": True}
                ],
                "error": str | None
            }

        A permission problem is reported honestly through `error`
        rather than being silently presented as an empty list.
        """

        return self.list_directory_contents(
            path, include_files=False
        )

    def list_directory_contents(
        self,
        path: str | None = None,
        *,
        include_files: bool = False,
        file_limit: int = 500,
    ) -> dict:
        """
        List subdirectories of `path` and, when
        include_files is true, the video/media files
        directly inside it (never recursive). Each file
        entry carries is_dir False plus a media flag so
        pickers can offer only analysable files:

            {"name": ..., "path": ...,
             "is_dir": False, "media": True}

        Non-media files are omitted. At most file_limit
        files are returned; truncation is reported
        honestly through `truncated` rather than
        silently. Directories are never truncated.
        """

        from app.scanner.scanner import is_video_file

        if not path or not str(path).strip():
            return {
                "current": None,
                "is_root": True,
                "parent": None,
                "entries": self.roots(),
                "files": [],
                "truncated": False,
                "error": None,
            }

        raw = str(path).strip()

        directory = Path(raw).expanduser()

        if not directory.is_dir():
            return {
                "current": raw,
                "is_root": False,
                "parent": self._parent_path(directory),
                "entries": [],
                "files": [],
                "truncated": False,
                "error": "The selected path is not an accessible "
                "directory.",
            }

        try:
            children = sorted(
                directory.iterdir(),
                key=lambda item: (not item.is_dir(), item.name.lower()),
            )
        except OSError as error:
            return {
                "current": raw,
                "is_root": False,
                "parent": self._parent_path(directory),
                "entries": [],
                "files": [],
                "truncated": False,
                "error": f"Could not read this directory: {error}",
            }

        entries = []
        files = []
        truncated = False

        for child in children:
            if child.is_dir():
                entries.append(
                    {
                        "name": child.name,
                        "path": str(child),
                        "is_dir": True,
                    }
                )
                continue

            if not include_files:
                continue

            try:
                if not is_video_file(child):
                    continue
            except OSError:
                continue

            if len(files) >= max(1, int(file_limit)):
                truncated = True
                continue

            files.append(
                {
                    "name": child.name,
                    "path": str(child),
                    "is_dir": False,
                    "media": True,
                }
            )

        return {
            "current": raw,
            "is_root": self._is_root(directory),
            "parent": self._parent_path(directory),
            "entries": entries,
            "files": files,
            "truncated": truncated,
            "error": None,
        }

    @staticmethod
    def _is_root(directory: Path) -> bool:
        return directory.parent == directory

    @staticmethod
    def _parent_path(directory: Path) -> str | None:
        parent = directory.parent
        if parent == directory:
            return None
        return str(parent)