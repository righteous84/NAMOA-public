"""Stable content-identity capture for source media.

Phase 18: SHA-256 is the authoritative content identity for
candidate-bearing analysis observations and for approval-time
validation. Hashing is deliberately scoped to analysis and approval
boundaries; queue and status reads use live metadata only.
"""

import hashlib
import os


class FileIdentityError(ValueError):
    """Raised when a stable content identity cannot be established."""


def sha256_file(path):
    """Return the SHA-256 digest of the file at `path`."""

    digest = hashlib.sha256()

    with open(path, "rb") as handle:

        for chunk in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def capture_sha256(
    path,
    *,
    expected_size_bytes=None,
    expected_file_mtime_ns=None,
    expected_inode=None,
):
    """
    Hash one file and prove the filesystem identity did not change
    across the read.

    Returns (sha256_hex, final_stat).

    The caller may supply the fingerprint the content must match.
    A mismatch before hashing means the caller's source snapshot is
    already stale. A mismatch between the pre-hash and post-hash
    stat means the file changed during hashing and the digest cannot
    be associated with one stable source state.

    This detects changes visible through size, mtime, and inode. It
    does not make the sequence atomic; a writer that changes bytes
    while preserving all three values is not detectable by metadata
    alone.
    """

    try:
        before = os.stat(path)
    except FileNotFoundError as error:
        raise FileIdentityError(
            f"source is missing: {path}"
        ) from error
    except OSError as error:
        raise FileIdentityError(
            f"source cannot be read reliably: {path} ({error})"
        ) from error

    if not os.path.isfile(path):
        raise FileIdentityError(
            f"source is not a regular file: {path}"
        )

    if (
        expected_size_bytes is not None
        and before.st_size != expected_size_bytes
    ):
        raise FileIdentityError(
            "source changed before content verification: "
            f"expected {expected_size_bytes} bytes, "
            f"found {before.st_size}"
        )

    if (
        expected_file_mtime_ns is not None
        and before.st_mtime_ns != expected_file_mtime_ns
    ):
        raise FileIdentityError(
            "source changed before content verification: "
            "modification time differs"
        )

    if (
        expected_inode is not None
        and before.st_ino != expected_inode
    ):
        raise FileIdentityError(
            "source changed before content verification: "
            "inode differs"
        )

    try:
        digest = sha256_file(path)
    except OSError as error:
        raise FileIdentityError(
            f"source cannot be read during content verification: "
            f"{path} ({error})"
        ) from error

    try:
        after = os.stat(path)
    except OSError as error:
        raise FileIdentityError(
            f"source disappeared during content verification: "
            f"{path} ({error})"
        ) from error

    if (
        after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
        or after.st_ino != before.st_ino
        or after.st_dev != before.st_dev
    ):
        raise FileIdentityError(
            "source changed during content verification; "
            "the SHA-256 digest cannot be associated with one "
            "stable source state"
        )

    return digest, after
