from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True, slots=True)
class FileObservation:
    """
    Immutable read model of one historical filesystem observation.

    Records exactly what NAMOA observed about a filesystem object
    at a particular point in time.

    This is a read model reconstructed from persisted state. It
    contains no persistence or business logic.
    """

    id: Optional[int] = None

    media_id: Optional[int] = None

    observed_at: Optional[str] = None

    file_path: str = ""

    file_name: Optional[str] = None

    file_extension: Optional[str] = None

    size_bytes: Optional[int] = None

    file_mtime_ns: Optional[int] = None

    filesystem_device: Optional[str] = None

    filesystem_inode: Optional[int] = None

    sha256_hash: Optional[str] = None

    identity_match_method: Optional[str] = None

    identity_evidence: dict = field(
        default_factory=dict
    )

    created_at: Optional[str] = None
