from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class InputSnapshot:
    """
    Immutable snapshot of the scanner input used for a single
    AnalysisRun.

    This captures the structured file attributes known to the
    scanner while preserving the complete raw scanner payload.

    No hashing, identity, duplicate detection, or comparison
    logic belongs in this model.
    """

    id: Optional[int] = None

    analysis_run_id: Optional[int] = None

    file_path: str = ""
    file_name: Optional[str] = None
    file_extension: Optional[str] = None

    size_bytes: Optional[int] = None
    file_hash: Optional[str] = None

    raw_scanner: Dict[str, Any] = field(
        default_factory=dict
    )

    captured_at: Optional[str] = None