"""
Per-transformation expected-outcome conversion layer (Phase 9).

Single owner for per-transformation expected-outcome conversion
arithmetic. Given transformation parameters a decision rule already
established and an observed source size, derive the expected saving
percent and expected saved bytes plus the recorded derivation basis.

Two constructors replicate the two live per-site constructions
exactly (see the Phase 9 instruction, canonical conversion rule):

- from_ratio: percent = round(ratio * 100, 1),
  bytes = int(size * ratio). The codec construction.
- from_percent: bytes = int(size * percent / 100), percent
  carried. The bitrate/audio/resolution/fallback construction.

Consistency: from_percent sites satisfy
bytes == int(size * percent / 100) exactly; from_ratio sites satisfy
abs(bytes - size * percent / 100) < size * 0.0005 + 1 (independent
rounding/truncation bound). No stronger universal invariant holds
for the live codec construction, and none is claimed.

What this layer does NOT own:

- domain parameters (reduction ratios, targets, shares, estimates):
  owned by the calling rules and knowledge
- whether a proposition is worthwhile (rules + user policy)
- proposition selection (FusionEngine)
- planning-time prediction (SavingsPredictionService, frozen)
- measured outcomes (execution)
- recommendation ordering or aggregate reporting (frozen)
- persistence, provenance recording, or presentation

The layer takes no opportunity scores, no policy, no confidence,
no knowledge lookups, and performs no I/O. It is deliberately a
leaf module: it imports nothing from the application so decision
rules, database repositories, and services can all consume it
without import cycles.
"""

from dataclasses import dataclass


#: Basis names recorded in signal evidence for derived numbers.
BASIS_FROM_RATIO = "from_ratio"
BASIS_FROM_PERCENT = "from_percent"
BASIS_FALLBACK = "percent_fallback"


@dataclass(frozen=True, slots=True)
class ConvertedSavings:
    """
    One atomic conversion result.

    percent is the expected saving percent (one decimal, as
    established by the caller for from_percent, derived here for
    from_ratio). saved_bytes is the expected absolute saving.
    basis names the constructor path. version is the conversion
    semantics in force.
    """

    percent: float

    saved_bytes: int

    basis: str

    version: str


class SavingsConversion:
    """
    Stateless per-transformation expected-outcome conversions.

    Semantic version of the conversion contract and rounding
    behaviour. A change to either constructor, the fallback
    formula, or the basis names MUST bump this version. Domain
    parameter values owned by rules are not part of this contract.
    """

    semantic_version = "1.0.0"

    # ---------------------------------------------------------
    # Constructors
    # ---------------------------------------------------------

    @staticmethod
    def from_ratio(ratio, size_bytes) -> ConvertedSavings:
        """
        Percent and bytes from an unrounded reduction ratio.

        Replicates the codec-rule construction exactly:
        percent = round(ratio * 100, 1),
        bytes = int(size * ratio).
        """

        percent = round(ratio * 100, 1)

        saved_bytes = int(size_bytes * ratio)

        return ConvertedSavings(
            percent=percent,
            saved_bytes=saved_bytes,
            basis=BASIS_FROM_RATIO,
            version=SavingsConversion.semantic_version,
        )

    @staticmethod
    def from_percent(percent, size_bytes) -> ConvertedSavings:
        """
        Bytes from an already-rounded percent.

        Replicates the bitrate/audio/resolution construction
        exactly: bytes = int(size * percent / 100), percent
        carried unchanged.
        """

        saved_bytes = int(size_bytes * percent / 100)

        return ConvertedSavings(
            percent=percent,
            saved_bytes=saved_bytes,
            basis=BASIS_FROM_PERCENT,
            version=SavingsConversion.semantic_version,
        )

    # ---------------------------------------------------------
    # Historical fallback
    # ---------------------------------------------------------

    @staticmethod
    def historical_fallback(saving_percent, size_bytes) -> int:
        """
        The historical percent-derived fallback as a single
        implementation of the exact legacy formula shared by the
        pipeline recommendation persistence and the opportunity
        repository candidate construction:

            int(size * ((percent or 0.0) / 100))

        Callers keep their own None-gating (authoritative bytes win
        when present); this function relocates only the formula.
        Historical rows keep NULLs where they have them.
        """

        return int(size_bytes * ((saving_percent or 0.0) / 100))
