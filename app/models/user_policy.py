"""
User policy model.

User preferences belong in policy, NOT in Expert conclusions and NOT
in factual observations. Policy influences acceptable trade-offs,
worthwhile-benefit thresholds, and planning parameters. It never
changes the underlying media facts or expert interpretation.

Aggressiveness semantics (documented, versioned):

    conservative
        Only recommend high-confidence opportunities with substantial
        expected benefit and low risk.

    standard
        Recommend credible opportunities with meaningful expected
        benefit and acceptable risk.

    aggressive
        Permit lower benefit thresholds and/or higher acceptable
        trade-offs within defined safety boundaries. Aggressive mode
        never disables safety controls, never permits execution
        without approval, and never overrides authoritative evidence.

Encoding-speed preference:

    Very Fast / Fast / Normal / Slow / Very Slow

    Encoding speed is a user preference. It cannot generally be
    inferred from media facts and NAMOA must not attempt to infer it.
    The preference influences optimisation planning and expected
    cost. When the user explicitly selects a speed, that value is
    policy, not intelligence.
"""

from dataclasses import dataclass, field

# Human-facing priority labels (§23) derived from opportunity level.
OPPORTUNITY_LEVEL_LABELS = {
    "none": "No recommendation",
    "weak": "Very Low",
    "meaningful": "Medium",
    "strong": "High",
}

# The semantic version of the user-policy meaning. Declared at module
# level because UserPolicy is a slots dataclass (its annotated fields
# become member descriptors on the class and are not directly
# readable as class attributes).
USER_POLICY_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class UserPolicy:
    """
    Immutable user optimisation policy.

    Every value here can change WHY a file becomes, or does not
    become, an optimisation candidate, what target is proposed, how
    valuable it is, or how the recommendation is prioritised. The
    policy therefore carries an explicit semantic version and
    participates in intelligence identity and provenance.
    """

    semantic_version: str = USER_POLICY_VERSION

    # Optimisation aggressiveness: conservative | standard | aggressive
    aggressiveness: str = "standard"

    # Minimum worthwhile expected storage saving (percent of the
    # file) below which a technical change is not worthwhile.
    min_worthwhile_saving_percent: float | None = None

    # Minimum worthwhile expected absolute saving (bytes). None means
    # no absolute floor (the percent threshold governs).
    min_worthwhile_saved_bytes: int | None = None

    # Preservation requirements.
    preserve_resolution: bool = True
    preserve_hdr: bool = True

    # Content-retention requirements (Phase 17 retention).
    # subtitle_retention: allow_loss | preserve. preserve makes
    # subtitle loss blocking-or-acknowledge at approval.
    # content_retention: normal | preserve_supported.
    # preserve_supported extends the same treatment to every
    # content class with a verified preservation contract; it
    # never promises literally every stream or metadata item.
    # Defaults reproduce pre-retention behaviour exactly.
    subtitle_retention: str = "allow_loss"
    content_retention: str = "normal"

    # Conversion permissions.
    permit_codec_conversion: bool = True
    permit_bitrate_reduction: bool = True
    permit_audio_conversion: bool = True
    permit_container_change: bool = True
    permit_resolution_reduction: bool = False

    # Maximum acceptable risk ceiling: low | medium | high. None means
    # the aggressiveness-derived ceiling applies. When explicitly set,
    # this value is authoritative over the aggressiveness default.
    acceptable_risk: str | None = None

    # Encoding-speed preference: very_fast | fast | normal | slow |
    # very_slow. A user preference, never inferred from media facts.
    encoding_speed: str = "normal"

    # ---------------------------------------------------------
    # Aggressiveness-derived defaults (versioned policy constants)
    # ---------------------------------------------------------

    #: Expected-saving percent threshold per aggressiveness level.
    AGGRESSIVENESS_MIN_SAVING_PERCENT = {
        "conservative": 25.0,
        "standard": 15.0,
        "aggressive": 8.0,
    }

    #: Minimum absolute expected saving (bytes) per aggressiveness
    #: level. A conversion whose absolute saving is below the floor is
    #: not worthwhile regardless of its percentage: a tiny file with a
    #: large percentage saving does not justify encoding cost and risk.
    AGGRESSIVENESS_MIN_SAVED_BYTES = {
        "conservative": 1024 * 1024 * 1024,  # 1 GiB
        "standard": 100 * 1024 * 1024,       # 100 MiB
        "aggressive": 0,
    }

    #: Maximum acceptable risk per aggressiveness level.
    AGGRESSIVENESS_MAX_RISK = {
        "conservative": "low",
        "standard": "medium",
        "aggressive": "high",
    }

    #: Minimum proposition confidence per aggressiveness level.
    AGGRESSIVENESS_MIN_CONFIDENCE = {
        "conservative": 0.70,
        "standard": 0.50,
        "aggressive": 0.40,
    }

    def effective_min_saving_percent(self) -> float:
        """
        The effective worthwhile-saving threshold: the explicit
        policy value when set, otherwise the aggressiveness default.
        """

        if self.min_worthwhile_saving_percent is not None:
            return float(self.min_worthwhile_saving_percent)

        return self.AGGRESSIVENESS_MIN_SAVING_PERCENT.get(
            self.aggressiveness,
            self.AGGRESSIVENESS_MIN_SAVING_PERCENT["standard"],
        )

    def effective_max_acceptable_risk(self) -> str:
        """
        The effective maximum acceptable risk: the explicit
        `acceptable_risk` ceiling when set, otherwise the
        aggressiveness-derived default. Aggressive mode raises the
        ceiling within defined boundaries; it never disables safety
        controls.
        """

        if self.acceptable_risk is not None:
            return self.acceptable_risk

        return self.AGGRESSIVENESS_MAX_RISK.get(
            self.aggressiveness,
            self.AGGRESSIVENESS_MAX_RISK["standard"],
        )

    def effective_min_confidence(self) -> float:
        """
        The effective minimum proposition confidence derived from
        aggressiveness.
        """

        return self.AGGRESSIVENESS_MIN_CONFIDENCE.get(
            self.aggressiveness,
            self.AGGRESSIVENESS_MIN_CONFIDENCE["standard"],
        )

    def effective_min_saved_bytes(self) -> int:
        """
        The effective minimum absolute saving (bytes): the explicit
        policy value when set, otherwise the aggressiveness default.
        """

        if self.min_worthwhile_saved_bytes is not None:
            return self.min_worthwhile_saved_bytes

        return self.AGGRESSIVENESS_MIN_SAVED_BYTES.get(
            self.aggressiveness,
            self.AGGRESSIVENESS_MIN_SAVED_BYTES["standard"],
        )

    def risk_acceptable(self, risk: str) -> bool:
        """
        Whether a proposition with the given risk category is
        acceptable under this policy.

        'unknown' risk is treated as the middle default (medium): the
        absence of a risk classification must not by itself suppress
        an otherwise valid proposition.
        """

        order = {"low": 1, "medium": 2, "high": 3, "unknown": 2}

        return order.get(risk, 2) <= order.get(
            self.effective_max_acceptable_risk(), 2
        )

    def worthwhile(
        self,
        saving_percent: float,
        saved_bytes: int | None = None,
    ) -> bool:
        """
        Whether an expected saving is worthwhile under this policy.

        Both the percent threshold and the absolute-byte floor must be
        met.
        """

        min_percent = self.effective_min_saving_percent()

        if saving_percent < min_percent:
            return False

        min_bytes = self.effective_min_saved_bytes()

        if saved_bytes is None:
            return False

        if saved_bytes < min_bytes:
            return False

        return True

    @classmethod
    def default(cls) -> "UserPolicy":
        """The standard default policy used when none is supplied."""
        return cls()

    def to_policy_payload(self) -> dict:
        """
        The attributable policy snapshot for provenance and
        intelligence identity.
        """

        return {
            "semantic_version": self.semantic_version,
            "aggressiveness": self.aggressiveness,
            "min_worthwhile_saving_percent": (
                self.min_worthwhile_saving_percent
            ),
            "min_worthwhile_saved_bytes": (
                self.min_worthwhile_saved_bytes
            ),
            "preserve_resolution": self.preserve_resolution,
            "preserve_hdr": self.preserve_hdr,
            "subtitle_retention": self.subtitle_retention,
            "content_retention": self.content_retention,
            "permit_codec_conversion": self.permit_codec_conversion,
            "permit_bitrate_reduction": self.permit_bitrate_reduction,
            "permit_audio_conversion": self.permit_audio_conversion,
            "permit_container_change": self.permit_container_change,
            "permit_resolution_reduction": (
                self.permit_resolution_reduction
            ),
            "acceptable_risk": self.acceptable_risk,
            "encoding_speed": self.encoding_speed,
            "effective_min_saving_percent": (
                self.effective_min_saving_percent()
            ),
            "effective_min_saved_bytes": (
                self.effective_min_saved_bytes()
            ),
            "effective_max_acceptable_risk": (
                self.effective_max_acceptable_risk()
            ),
            "effective_min_confidence": (
                self.effective_min_confidence()
            ),
        }