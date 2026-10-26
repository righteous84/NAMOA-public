"""
Organisation PREFERENCES (Phase 13).

User-facing metadata, tag, naming, and classification
preferences for the organisation domain.

Preferences are NOT intelligence and NOT policy values
themselves: they are operator-owned inputs that RESOLVE into
an effective OrganisationPolicy through
`resolve_effective_policy`, and their payload is snapshotted
verbatim alongside the policy values of every decision run
they influence, so each proposal remains attributable to the
exact preferences that produced it.

Semantics:

- classification_proposals "propose" (default): library
  classification may propose category destinations (current
  behaviour). "ignore": the classification rule component
  is scoped out for the run, so no classification-driven
  destination, rename, grouping, or ordering intent is
  proposed; duplicate evidence is unaffected.
- naming_style "normalised" (default): separator
  normalisation may propose renames (current behaviour).
  "preserve": no rename intent is ever proposed.
- duplicate_proposals "flag" (default): hash-confirmed
  duplicate candidates are proposed (current behaviour).
  "ignore": no duplicate intent is ever proposed.
- grouping_proposals "propose" (default): grouping and
  ordering intents are proposed (current behaviour).
  "ignore": no grouping or ordering intent is ever proposed.
- metadata_domains: the observed filename-attribute domains
  that participate in organisation evidence. Default is all
  four current domains (current behaviour). A subset narrows
  the observed metadata cited by proposals; it never invents
  metadata.

Preferences never approve, never execute, and never touch
the filesystem. They only shape which proposals a decision
run may produce. Approval remains an explicit per-proposal
human action; execution remains behind the organisation
execution authority.
"""

from dataclasses import dataclass, field


#: Semantic version of the preference meaning. A change that
#: can alter which proposals a preference value produces MUST
#: bump this version.
PREFERENCES_VERSION = "1.0.0"

#: Closed naming-style set.
NAMING_NORMALISED = "normalised"

NAMING_PRESERVE = "preserve"

NAMING_STYLES = frozenset({NAMING_NORMALISED, NAMING_PRESERVE})

#: Closed classification-proposal set.
CLASSIFICATION_PROPOSE = "propose"

CLASSIFICATION_IGNORE = "ignore"

CLASSIFICATION_MODES = frozenset(
    {CLASSIFICATION_PROPOSE, CLASSIFICATION_IGNORE}
)

#: Closed duplicate-proposal set.
DUPLICATES_FLAG = "flag"

DUPLICATES_IGNORE = "ignore"

DUPLICATE_MODES = frozenset({DUPLICATES_FLAG, DUPLICATES_IGNORE})

#: Closed grouping-proposal set.
GROUPING_PROPOSE = "propose"

GROUPING_IGNORE = "ignore"

GROUPING_MODES = frozenset({GROUPING_PROPOSE, GROUPING_IGNORE})

#: Closed observed-metadata domain set. These are the filename
#: attribute domains the shared classification evidence builder
#: distils; preferences select a subset, never new domains.
METADATA_DOMAINS = frozenset(
    {"source", "release", "resolution", "video_codec"}
)

DEFAULT_METADATA_DOMAINS = tuple(sorted(METADATA_DOMAINS))


@dataclass(frozen=True, slots=True)
class OrganisationPreferences:
    """
    Immutable organisation preferences.

    Every value is validated against its closed set; unknown
    values raise ValueError and never silently fall back.
    """

    semantic_version: str = PREFERENCES_VERSION

    classification_proposals: str = CLASSIFICATION_PROPOSE

    naming_style: str = NAMING_NORMALISED

    duplicate_proposals: str = DUPLICATES_FLAG

    grouping_proposals: str = GROUPING_PROPOSE

    metadata_domains: tuple = field(
        default_factory=lambda: DEFAULT_METADATA_DOMAINS
    )

    def __post_init__(self):

        if self.classification_proposals not in (
            CLASSIFICATION_MODES
        ):

            raise ValueError(
                f"unknown classification_proposals "
                f"'{self.classification_proposals}' "
                f"(expected one of "
                f"{sorted(CLASSIFICATION_MODES)})"
            )

        if self.naming_style not in NAMING_STYLES:

            raise ValueError(
                f"unknown naming_style "
                f"'{self.naming_style}' (expected one of "
                f"{sorted(NAMING_STYLES)})"
            )

        if self.duplicate_proposals not in DUPLICATE_MODES:

            raise ValueError(
                f"unknown duplicate_proposals "
                f"'{self.duplicate_proposals}' (expected one "
                f"of {sorted(DUPLICATE_MODES)})"
            )

        if self.grouping_proposals not in GROUPING_MODES:

            raise ValueError(
                f"unknown grouping_proposals "
                f"'{self.grouping_proposals}' (expected one "
                f"of {sorted(GROUPING_MODES)})"
            )

        domains = tuple(self.metadata_domains or ())

        unknown = [
            domain for domain in domains if (
                domain not in METADATA_DOMAINS
            )
        ]

        if unknown:

            raise ValueError(
                f"unknown metadata domains {sorted(unknown)} "
                f"(expected a subset of "
                f"{sorted(METADATA_DOMAINS)})"
            )

        # Canonical order so equal preferences always produce
        # equal payloads and digests.
        object.__setattr__(
            self,
            "metadata_domains",
            tuple(sorted(set(domains))),
        )

    def to_preference_payload(self) -> dict:
        """
        The attributable preference snapshot recorded verbatim
        in the decision-run policy values.
        """

        return {
            "semantic_version": self.semantic_version,
            "classification_proposals": (
                self.classification_proposals
            ),
            "naming_style": self.naming_style,
            "duplicate_proposals": self.duplicate_proposals,
            "grouping_proposals": self.grouping_proposals,
            "metadata_domains": list(self.metadata_domains),
        }


def default_preferences() -> OrganisationPreferences:
    """
    The default preferences, reproducing current behaviour
    exactly when resolved.
    """

    return OrganisationPreferences()


def resolve_effective_policy(
    base_policy,
    preferences: OrganisationPreferences | None,
):
    """
    Resolve the effective OrganisationPolicy for a decision
    run under the given preferences.

    Returns the base policy unchanged when preferences are
    None or when they suppress nothing, so the default path
    produces byte-identical snapshots. Otherwise returns an
    equivalent policy whose enabled-rule selection excludes
    the suppressed rule components; library roots are always
    preserved verbatim.
    """

    from app.organisation.rules import (
        DuplicateDetectionRules,
        GroupingRules,
        LibraryClassificationRules,
        NamingConsistencyRules,
        OrderingRules,
        RULE_COMPONENT_CLASSES,
    )

    if preferences is None:

        return base_policy

    suppressed = set()

    if preferences.classification_proposals == (
        CLASSIFICATION_IGNORE
    ):

        suppressed.add(LibraryClassificationRules.name)

    if preferences.naming_style == NAMING_PRESERVE:

        suppressed.add(NamingConsistencyRules.name)

    if preferences.duplicate_proposals == DUPLICATES_IGNORE:

        suppressed.add(DuplicateDetectionRules.name)

    if preferences.grouping_proposals == GROUPING_IGNORE:

        suppressed.add(GroupingRules.name)

        suppressed.add(OrderingRules.name)

    if not suppressed:

        return base_policy

    base_enabled = base_policy.enabled_rules

    if base_enabled is None:

        effective_enabled = tuple(
            component.name
            for component in RULE_COMPONENT_CLASSES
            if component.name not in suppressed
        )

    else:

        effective_enabled = tuple(
            name for name in base_enabled if (
                name not in suppressed
            )
        )

    from app.organisation.policy import OrganisationPolicy

    return OrganisationPolicy(
        library_roots=tuple(base_policy.library_roots),
        enabled_rules=effective_enabled,
    )
