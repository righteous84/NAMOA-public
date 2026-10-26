"""
Organisation POLICY (Sprint 13).

Policy is operator-owned configuration that SELECTS and SCOPES
the versioned organisation rules. It is deliberately kept
separate from INTELLIGENCE:

- the rule components themselves are versioned intelligence
  (app/organisation/rules.py)
- policy values (library roots, enabled rules) are captured
  verbatim in every decision-run snapshot so each decision's
  effective inputs are reconstructable, exactly like
  RULE_WEIGHTS for optimisation

Arbitrary UI preferences (page ordering, display labels) are
neither intelligence nor policy and are never versioned.
"""

from dataclasses import dataclass, field

import hashlib
import json


@dataclass(frozen=True)
class OrganisationPolicy:
    """
    Immutable organisation policy configuration.

    library_roots:
        Destination roots under which the destination template
        rules propose category directories. Purely lexical in
        Sprint 13: generation NEVER touches the filesystem,
        including for existence checks. Root validation is an
        execution-boundary concern (Sprint 14).

    enabled_rules:
        Names of rule components participating in decisions.
        None means all declared rules are enabled. Selection is
        captured per decision run; it can change results and is
        therefore part of the snapshot, but it is not itself a
        versioned component.
    """

    library_roots: tuple[str, ...] = ()

    enabled_rules: tuple[str, ...] | None = None

    def with_rules(self, *names: str) -> "OrganisationPolicy":
        """
        Derived policy selecting exactly the named rules.
        Used by callers that scope a decision run.
        """

        return OrganisationPolicy(
            library_roots=self.library_roots,
            enabled_rules=tuple(names),
        )

    def policy_values(self) -> dict:
        """
        Canonical snapshot payload of the effective policy.
        """

        return {
            "library_roots": list(self.library_roots),
            "enabled_rules": (
                list(self.enabled_rules)
                if self.enabled_rules is not None
                else None
            ),
        }


# Default operator policy: no roots configured, all rules
# enabled. Duplicate detection works without roots; destination,
# grouping and ordering proposals require configured roots.
DEFAULT_ORGANISATION_POLICY = OrganisationPolicy()


def rule_manifest(
    enabled_rules: tuple[str, ...] | list | None = None,
) -> dict:
    """
    The semantic-version manifest of the rule components that a
    decision run consults, honouring the enabled selection.
    """

    from app.organisation.rules import RULE_COMPONENT_CLASSES

    manifest = {}

    for component_class in RULE_COMPONENT_CLASSES:

        if (
            enabled_rules is not None
            and component_class.name not in enabled_rules
        ):
            continue

        manifest[component_class.name] = (
            component_class.semantic_version
        )

    return dict(sorted(manifest.items()))


def organisation_identity_digest(
    rule_versions: dict,
    policy_values: dict,
) -> str:
    """
    Deterministic sha256 digest of the canonical ORGANISATION
    identity payload (rule versions + policy values).

    This is a separate domain digest from the ANALYSIS
    intelligence identity: changing organisation rules or policy
    changes organisation decisions and their attribution, but
    must never invalidate analyses.

    Equal inputs always produce an equal digest; any relevant
    change produces a different one.
    """

    payload = {
        "schema": "namoa-organisation-identity/1",
        "rule_versions": dict(
            sorted((rule_versions or {}).items())
        ),
        "policy_values": policy_values,
    }

    canonical_json = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical_json.encode("utf-8")
    ).hexdigest()
