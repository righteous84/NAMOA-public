"""
Optimisation planning semantics (focused correction).

Establishes the underlying planning/cost semantics for the
encoding-speed preference so it has actual analytical/planning meaning
rather than appearing only in recommendation text.

Semantics:

    user encoding-speed preference
        -> encoding strategy class
        -> compression-efficiency consequence
        -> expected encoding-cost category
        -> relative encoding-time factor (unit-less, Normal = 1.0)

Encoding speed is a USER PREFERENCE. It is never inferred from media
facts. The mapping below is a versioned planning policy: it defines
how a selected speed affects expected cost/time/strategy for a
re-encoding optimisation, and it participates in the intelligence
identity and run provenance.

No false precision is produced: exact elapsed time is not fabricated.
Only a documented relative factor and cost category are emitted, and
the plan records whether the speed applies to the chosen operation (a
stream-copy remux performs no re-encoding, so the speed is not
applicable there).

Cost semantics (documented, versioned):

    very_fast   minimal encoding effort; low compression efficiency;
                low cost category; lowest relative time
    fast        low encoding effort; low-moderate compression;
                low cost category; low relative time
    normal      balanced encoding; moderate compression; medium cost
                category; reference relative time (1.0)
    slow        high encoding effort; high compression efficiency;
                high cost category; high relative time
    very_slow   maximum encoding effort; very high compression
                efficiency; high cost category; highest relative time
"""

from dataclasses import dataclass

# Semantic version of the planning-policy meaning. A semantic change
# (a mapping value, cost category, relative factor or strategy that
# can alter planning/cost meaning) MUST bump this version.
PLANNING_POLICY_VERSION = "1.0.0"

# Operations that perform re-encoding, where the encoding-speed
# preference directly affects planning/cost semantics.
RE_ENCODING_PROPOSITIONS = frozenset(
    {
        "codec_conversion",
        "bitrate_reduction",
        "audio_conversion",
        "resolution_reduction",
    }
)

# Stream-copy / container operations, where no re-encoding occurs and
# the encoding-speed preference is not applicable.
COPY_PROPOSITIONS = frozenset({"container_remux"})


class EncodingSpeedPolicy:
    """
    Versioned planning policy mapping the user encoding-speed
    preference to planning/cost semantics.
    """

    semantic_version = PLANNING_POLICY_VERSION

    #: speed -> semantics. relative_time_factor is unit-less relative
    #: to Normal = 1.0. cost_category and compression_efficiency are
    #: semantic categories, never false precision.
    SPEED_SEMANTICS = {
        "very_fast": {
            "label": "Very Fast",
            "strategy": "minimal encoding effort (e.g. veryfast preset)",
            "compression_efficiency": "low",
            "cost_category": "low",
            "relative_time_factor": 0.25,
        },
        "fast": {
            "label": "Fast",
            "strategy": "low encoding effort (e.g. fast preset)",
            "compression_efficiency": "low-moderate",
            "cost_category": "low",
            "relative_time_factor": 0.5,
        },
        "normal": {
            "label": "Normal",
            "strategy": "balanced encoding (e.g. medium preset)",
            "compression_efficiency": "moderate",
            "cost_category": "medium",
            "relative_time_factor": 1.0,
        },
        "slow": {
            "label": "Slow",
            "strategy": "high encoding effort (e.g. slow preset)",
            "compression_efficiency": "high",
            "cost_category": "high",
            "relative_time_factor": 2.0,
        },
        "very_slow": {
            "label": "Very Slow",
            "strategy": "maximum encoding effort (e.g. veryslow preset)",
            "compression_efficiency": "very high",
            "cost_category": "high",
            "relative_time_factor": 4.0,
        },
    }

    @classmethod
    def speed_semantics(cls, encoding_speed: str) -> dict:
        """
        The planning semantics for a speed preference, or the Normal
        semantics for an unrecognised value (fail-safe, never an
        error: the mapping is closed and documented).
        """

        return cls.SPEED_SEMANTICS.get(
            encoding_speed,
            cls.SPEED_SEMANTICS["normal"],
        )

    @classmethod
    def applies_to(cls, proposition: str) -> bool:
        """
        Whether the encoding-speed preference affects planning for a
        proposition. Re-encoding operations apply; stream-copy
        operations (container remux) do not.
        """

        if proposition in RE_ENCODING_PROPOSITIONS:
            return True
        if proposition in COPY_PROPOSITIONS:
            return False
        # Unknown proposition: default to applicable is unsafe; a
        # container-style copy is the only currently executable
        # operation, so the conservative default is not-applicable.
        return False

    @classmethod
    def planning_semantics_for(
        cls,
        user_policy,
        proposition: str,
    ) -> dict:
        """
        The planning/cost semantics for a proposition under a user
        policy. Returns a structured, versioned payload that the plan
        record carries.
        """

        speed = getattr(user_policy, "encoding_speed", "normal")

        semantics = cls.speed_semantics(speed)

        applies = cls.applies_to(proposition)

        return {
            "planning_policy_version": cls.semantic_version,
            "encoding_speed": speed,
            "speed_applies": applies,
            "strategy": (
                semantics["strategy"]
                if applies
                else (
                    "no re-encoding: stream-copy operation; "
                    "encoding speed not applicable"
                )
            ),
            "compression_efficiency": (
                semantics["compression_efficiency"]
                if applies
                else None
            ),
            "cost_category": (
                semantics["cost_category"]
                if applies
                else "low"
            ),
            "relative_time_factor": (
                semantics["relative_time_factor"]
                if applies
                else None
            ),
        }

    @classmethod
    def policy_values(cls) -> dict:
        """
        The attributable planning-policy snapshot: the mapping and its
        version. Participates in the intelligence identity and run
        provenance.
        """

        return {
            "version": cls.semantic_version,
            "re_encoding_propositions": sorted(
                RE_ENCODING_PROPOSITIONS
            ),
            "copy_propositions": sorted(COPY_PROPOSITIONS),
            "speed_semantics": cls.SPEED_SEMANTICS,
        }