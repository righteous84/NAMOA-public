from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ConfigurationSnapshot:
    """
    Immutable snapshot of the NAMOA runtime configuration used
    for a single AnalysisRun.

    The configuration is intentionally stored as a single
    structured payload so new configuration areas can be added
    without changing the database schema.

    This model is a transport object only and contains no
    persistence or business logic.
    """

    id: Optional[int] = None

    configuration: Dict[str, Any] = field(
        default_factory=dict
    )

    created_at: Optional[str] = None