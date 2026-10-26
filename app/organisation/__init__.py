"""
NAMOA Library Organisation intelligence domain (Sprint 13).

A SEPARATE intelligence domain from optimisation. It may share
infrastructure (e.g. filename evidence parsing) but never shares
or mutates optimisation semantics, and it performs ZERO
filesystem mutation: Sprint 13 ends at the organisation
recommendation/proposal boundary.

Layout:

- policy.py      operator-owned configuration (POLICY), snapshotted
                 per decision run, never treated as intelligence
- rules.py       versioned deterministic rule components
                 (INTELLIGENCE)
- evidence.py    organisation evidence derived ONLY from persisted
                 filesystem observations (EVIDENCE; no scanning)
- intelligence.py  decision-run anchor, identity digest, and the
                 deterministic proposal-generation authority
"""

from app.organisation.policy import (
    DEFAULT_ORGANISATION_POLICY,
    OrganisationPolicy,
    organisation_identity_digest,
    rule_manifest,
)
from app.organisation.rules import (
    RULE_COMPONENT_CLASSES,
)
from app.organisation.intelligence import (
    OrganisationIntelligenceService,
)

__all__ = [
    "DEFAULT_ORGANISATION_POLICY",
    "OrganisationPolicy",
    "organisation_identity_digest",
    "rule_manifest",
    "RULE_COMPONENT_CLASSES",
    "OrganisationIntelligenceService",
]
