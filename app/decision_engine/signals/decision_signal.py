from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class DecisionSignal:
    """
    Output produced by Decision Rules.

    Represents a decision proposition detected from Expert
    intelligence. A signal is a meaningful, explainable proposition,
    not merely a numeric direction.

    Semantics of the proposition fields:

        proposition
            Machine key naming the proposition domain this signal
            belongs to (for example "codec_conversion",
            "bitrate_reduction", "audio_conversion",
            "container_remux", "resolution_reduction"). Fusion uses
            it to reconcile corroborating and contradictory signals.

        current_state
            WHAT is currently present (for example "H264",
            "12 Mbps", "1080p", "TRUEHD").

        target_state
            WHAT the proposition proposes (for example "HEVC"),
            or None for a preservation/constraint signal.

        benefit
            Expected benefit category of the proposition:
            none / small / moderate / substantial.

        cost
            Expected cost category of the proposition:
            none / low / moderate / high.

        risk
            Expected risk category of the proposition:
            low / medium / high / unknown.

        reason
            Human-readable explanation of WHY the rule reached this
            conclusion.

        direction
            optimize | remux : an opportunity proposition
            preserve       : a preservation / constraint conclusion

        compatibility_effect
            improves | neutral | worsens | unknown : what the
            proposed transformation does to compatibility,
            independent of its storage benefit. Defaults to
            unknown; unknown must never be read as compatible.
            compatibility_evidence carries the basis.

    confidence represents how certain the intelligence is in this
    conclusion. opportunity_score represents how valuable the
    proposition appears; it is NOT the same concept as confidence.
    """

    rule: str

    opportunity_score: float

    confidence: float = 1.0

    direction: str = "optimize"

    notes: str = ""

    evidence: Dict[str, Any] = field(
        default_factory=dict
    )

    provenance: Dict[str, Any] = field(
        default_factory=dict
    )

    proposition: str = ""

    current_state: Optional[str] = None

    target_state: Optional[str] = None

    benefit: str = "none"

    cost: str = "none"

    risk: str = "unknown"

    reason: str = ""

    compatibility_effect: str = "unknown"

    compatibility_evidence: Dict[str, Any] = field(
        default_factory=dict
    )