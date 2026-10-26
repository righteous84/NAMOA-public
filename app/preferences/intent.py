"""
User Media Intent domain (Phase 15, Phase C, version 1.0.0).

Human-facing optimisation intent: what the user wants their media
library to achieve, expressed without technical media-engineering
vocabulary. Intent never enters decision rules directly; it compiles
into existing UserPolicy constraints plus derived-constraint records
(see app/preferences/policy.py).

Three closed axes, each with fixed meanings recorded here so presets,
derivation, wording, and tests share one definition.
"""

from dataclasses import dataclass


# Semantic version of the intent vocabulary and its documented
# meanings. Adding, removing, or redefining a value MUST bump this
# version in the same change.
INTENT_VERSION = "1.0.0"

COMPATIBILITY_TARGETS = frozenset({
    "Maximum",
    "Broad",
    "Efficient",
})

QUALITY_CEILINGS = frozenset({
    "Original",
    "4K",
    "1080p",
    "720p",
    "EfficiencyFirst",
})

OPTIMISATION_PREFERENCES = frozenset({
    "Conservative",
    "Balanced",
    "Aggressive",
})

DEFAULT_COMPATIBILITY = "Broad"
DEFAULT_QUALITY_CEILING = "1080p"
DEFAULT_OPTIMISATION = "Balanced"


@dataclass(frozen=True, slots=True)
class UserIntent:
    """
    One explicit statement of what the user wants.

    compatibility : Maximum (outputs for virtually any client;
        efficiency transforms forbidden), Broad (modern clients;
        unknown effects proceed with caveat), or Efficient
        (best compression first; narrower support accepted).
    quality_ceiling : maximum resolution worth retaining. Original
        forbids quality-reducing transforms; 4K/1080p/720p bound
        eligible reductions; EfficiencyFirst imposes no ceiling.
        A ceiling is never an output-resolution target and never
        authorises upscaling.
    optimisation : Conservative, Balanced, or Aggressive appetite
        for pursuing storage savings; maps onto the existing
        aggressiveness contract, never a parallel dial.
    """

    compatibility: str = DEFAULT_COMPATIBILITY

    quality_ceiling: str = DEFAULT_QUALITY_CEILING

    optimisation: str = DEFAULT_OPTIMISATION

    def __post_init__(self):
        if self.compatibility not in COMPATIBILITY_TARGETS:
            raise ValueError(
                f"unknown compatibility target "
                f"'{self.compatibility}' (expected one of "
                f"{sorted(COMPATIBILITY_TARGETS)})"
            )

        if self.quality_ceiling not in QUALITY_CEILINGS:
            raise ValueError(
                f"unknown quality ceiling "
                f"'{self.quality_ceiling}' (expected one of "
                f"{sorted(QUALITY_CEILINGS)})"
            )

        if self.optimisation not in OPTIMISATION_PREFERENCES:
            raise ValueError(
                f"unknown optimisation preference "
                f"'{self.optimisation}' (expected one of "
                f"{sorted(OPTIMISATION_PREFERENCES)})"
            )

    @classmethod
    def default(cls) -> "UserIntent":
        """The default intent: Broad, 1080p, Balanced."""

        return cls()

    def to_dict(self) -> dict:
        return {
            "compatibility": self.compatibility,
            "quality_ceiling": self.quality_ceiling,
            "optimisation": self.optimisation,
            "intent_version": INTENT_VERSION,
        }
