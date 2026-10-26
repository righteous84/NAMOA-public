"""Live filesystem state probe for currentness reads.

Phase 18: queue and library-status reads must present the filesystem
state observed at the read boundary to AnalysisValidityService.

This module owns only the filesystem probe. It deliberately does not
decide analysis validity; that remains the sole authority of
AnalysisValidityService.
"""

import errno
import os
from dataclasses import dataclass


STATE_PRESENT = "present"
STATE_MISSING = "missing"
STATE_UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class CurrentFileState:
    """One live filesystem observation."""

    state: str

    size_bytes: int | None = None

    file_mtime_ns: int | None = None

    filesystem_device: int | None = None

    filesystem_inode: int | None = None

    detail: str | None = None


def probe_current_file(path) -> CurrentFileState:
    """
    Observe the live filesystem object at `path`.

    - present: a regular file was statted
    - missing: the path is confirmed absent
    - unavailable: the path could not be inspected reliably
      (permission, I/O, transport, or another error)

    A confirmed missing path is never inferred from an inspection
    failure. This distinction prevents an unavailable mount from
    being reported as deleted media.
    """

    try:

        stat = os.stat(path)

    except FileNotFoundError:

        return CurrentFileState(
            state=STATE_MISSING,
            detail="path does not exist",
        )

    except OSError as error:

        if error.errno in (errno.ENOENT, errno.ENOTDIR):

            return CurrentFileState(
                state=STATE_MISSING,
                detail=str(error),
            )

        return CurrentFileState(
            state=STATE_UNAVAILABLE,
            detail=str(error),
        )

    if not os.path.isfile(path):

        return CurrentFileState(
            state=STATE_UNAVAILABLE,
            detail="path is not a regular file",
        )

    return CurrentFileState(
        state=STATE_PRESENT,
        size_bytes=stat.st_size,
        file_mtime_ns=stat.st_mtime_ns,
        filesystem_device=stat.st_dev,
        filesystem_inode=stat.st_ino,
    )
