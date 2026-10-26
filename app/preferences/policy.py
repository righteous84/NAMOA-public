"""
Intent and preference to policy derivation (Phase 15, Phase C,
version 1.0.0).

Pure deterministic compilation of human intent plus matched
preference answers into an existing UserPolicy. The result is
always equal-to-or-narrower-than the base policy: permits can only
be revoked, risk ceilings only lowered, preserves only enabled,
worthwhile floors only raised (via aggressiveness), and
aggressiveness/encoding_speed only moved toward less permissive.

Nothing here widens, invents, or weakens. Quality ceilings other
than Original have no UserPolicy field that can represent a
target-bounded reduction, so they produce no policy change; that
limitation is explicit and reported, never silently worked around.
"""

from dataclasses import dataclass, replace
from typing import Iterable, Mapping

from app.models.user_policy import UserPolicy
from app.preferences.intent import UserIntent


# Semantic version of the derivation behaviour (mappings,
# merge order, narrowing proof). Any change MUST bump this version
# in the same change.
POLICY_DERIVATION_VERSION = "1.0.0"

#: Permissiveness order for the optimisation axis. Lower means
#: fewer things qualify, therefore narrower.
PERMISSIVENESS_ORDER = {
    "conservative": 0,
    "standard": 1,
    "aggressive": 2,
}

#: UserIntent optimisation vocabulary mapped onto the existing
#: aggressiveness contract. Balanced and standard name the same
#: appetite in the two vocabularies.
INTENT_OPTIMISATION_TO_AGGRESSIVENESS = {
    "Conservative": "conservative",
    "Balanced": "standard",
    "Aggressive": "aggressive",
}

_RISK_ORDER = {
    "low": 0,
    "medium": 1,
    "high": 2,
}

_CONVERSION_PERMITS = (
    "permit_codec_conversion",
    "permit_bitrate_reduction",
    "permit_audio_conversion",
    "permit_container_change",
    "permit_resolution_reduction",
)


@dataclass(frozen=True, slots=True)
class PreferenceConstraint:
    """
    One matched preference rule reduced to its policy effect.

    rule_id : stable identity of the matched preference rule.
    answer  : the rule's canonical answer. Keep revokes conversion
        permits, floors risk at low, and enables preserves.
        Balanced caps appetite at standard. Optimise and
        Leave-alone carry no policy effect.
    """

    rule_id: str

    answer: str

    def __post_init__(self):
        from app.preferences.dimensions import ANSWERS

        if not isinstance(self.rule_id, str) or not self.rule_id:
            raise ValueError(
                "rule_id must be a non-empty string"
            )

        if self.answer not in ANSWERS:
            raise ValueError(
                f"unknown preference answer '{self.answer}'"
            )


def _narrower_risk(first: str, second: str) -> str:
    if _RISK_ORDER[second] < _RISK_ORDER[first]:
        return second
    return first


def _narrower_aggressiveness(first: str, second: str) -> str:
    if PERMISSIVENESS_ORDER[second] < PERMISSIVENESS_ORDER[first]:
        return second
    return first


def is_narrower_or_equal(result: UserPolicy, base: UserPolicy) -> bool:
    """
    Proof helper: every gate in result is equal to or narrower than
    the corresponding gate in base. Permits may only go True to
    False, risk ceilings only down the low/medium/high ladder,
    preserves only False to True, worthwhile floors only up, and
    aggressiveness/encoding_speed only toward less permissive.
    """

    for field_name in _CONVERSION_PERMITS:
        if getattr(result, field_name) and not getattr(
            base, field_name
        ):
            return False

    if _RISK_ORDER[result.effective_max_acceptable_risk()] > (
        _RISK_ORDER[base.effective_max_acceptable_risk()]
    ):
        return False

    if result.effective_min_saving_percent() < (
        base.effective_min_saving_percent()
    ):
        return False

    if result.effective_min_saved_bytes() < (
        base.effective_min_saved_bytes()
    ):
        return False

    if base.preserve_resolution and not result.preserve_resolution:
        return False

    if base.preserve_hdr and not result.preserve_hdr:
        return False

    if (
        PERMISSIVENESS_ORDER[result.aggressiveness]
        > PERMISSIVENESS_ORDER[base.aggressiveness]
    ):
        return False

    if result.encoding_speed != base.encoding_speed:
        return False

    return True


def resolve_effective_policy(
    base_policy: UserPolicy,
    preference_constraints,
    file_facts: Mapping,
) -> UserPolicy:
    """
    Derive the effective policy for one file evaluation.

    Inputs: the operator-configured base policy, an iterable of
    PreferenceConstraint (matched preference rules for this file;
    empty means no preference evidence), and the file facts mapping
    (structurally validated; attribution of which facts mattered
    lives in the matched rules, not here).

    Output: a standard UserPolicy that is provably
    equal-to-or-narrower-than the base (see
    is_narrower_or_equal). Intent axes map as follows: Maximum
    compatibility revokes all conversion permits, floors risk at
    low, and enables preserves; Broad caps risk at medium;
    Efficient carries no narrowing; Original quality revokes
    resolution reduction and enables resolution preservation (other
    ceilings have no UserPolicy representation and are an explicit
    documented limitation); optimisation caps aggressiveness at the
    intent level. Keep answers revoke permits, floor risk at low,
    and enable preserves; Balanced answers cap appetite at
    standard; Optimise and Leave-alone carry no policy effect.
    """

    if not isinstance(base_policy, UserPolicy):
        raise ValueError("base_policy must be a UserPolicy")

    if not isinstance(file_facts, Mapping):
        raise ValueError("file_facts must be a mapping")

    constraints = list(preference_constraints or [])

    intent = None
    answers = set()

    for constraint in constraints:
        if isinstance(constraint, UserIntent):
            if intent is not None:
                raise ValueError(
                    "at most one UserIntent per derivation"
                )
            intent = constraint
            continue

        if not isinstance(constraint, PreferenceConstraint):
            raise ValueError(
                "preference_constraints must contain only "
                "UserIntent or PreferenceConstraint entries"
            )

        answers.add(constraint.answer)

    if intent is None:
        intent = UserIntent.default()

    permits = {
        field_name: getattr(base_policy, field_name)
        for field_name in _CONVERSION_PERMITS
    }

    risk = base_policy.effective_max_acceptable_risk()
    aggressiveness = base_policy.aggressiveness
    preserve_resolution = base_policy.preserve_resolution
    preserve_hdr = base_policy.preserve_hdr

    if intent.compatibility == "Maximum":
        for field_name in permits:
            permits[field_name] = False
        risk = _narrower_risk(risk, "low")
        preserve_resolution = True
        preserve_hdr = True
    elif intent.compatibility == "Broad":
        risk = _narrower_risk(risk, "medium")

    if intent.quality_ceiling == "Original":
        permits["permit_resolution_reduction"] = False
        preserve_resolution = True

    aggressiveness = _narrower_aggressiveness(
        aggressiveness,
        INTENT_OPTIMISATION_TO_AGGRESSIVENESS[intent.optimisation],
    )

    if "Keep" in answers:
        for field_name in permits:
            permits[field_name] = False
        risk = _narrower_risk(risk, "low")
        preserve_resolution = True
        preserve_hdr = True

    if "Balanced" in answers:
        aggressiveness = _narrower_aggressiveness(
            aggressiveness, "standard"
        )

    result = replace(
        base_policy,
        **permits,
        acceptable_risk=(
            None
            if risk == _risk_default_for(base_policy, aggressiveness)
            and base_policy.acceptable_risk is None
            else risk
        ),
        preserve_resolution=preserve_resolution,
        preserve_hdr=preserve_hdr,
        aggressiveness=aggressiveness,
    )

    return result


def _risk_default_for(policy: UserPolicy, aggressiveness: str) -> str:
    table = UserPolicy.AGGRESSIVENESS_MAX_RISK
    return table.get(aggressiveness, table["standard"])
