"""
NAMOA intelligence versioning package.

Single source of truth for semantic version identity of the
intelligence components that produce persisted analytical meaning.

The version is declared on each component class (semantic_version) and
collected here into a run-level manifest for persistence. A semantic
change to any versioned component MUST be accompanied by a version
bump so that historical records never ambiguously refer to multiple
meanings of the same version.
"""

from app.versioning.registry import (
    PIPELINE_VERSION,
    VERSIONED_EXPERTS,
    VERSIONED_RULES,
    build_component_versions,
    build_policy_values,
    canonical_intelligence_identity,
    evidence_weight_policy,
    get_git_revision,
    intelligence_identity_digest,
    recommendation_policy,
    recommendation_semantics_policy,
    user_policy,
    planning_policy,
    library_policy,
    fusion_policy,
    version_inventory,
)

__all__ = [
    "PIPELINE_VERSION",
    "VERSIONED_EXPERTS",
    "VERSIONED_RULES",
    "build_component_versions",
    "build_policy_values",
    "canonical_intelligence_identity",
    "evidence_weight_policy",
    "get_git_revision",
    "intelligence_identity_digest",
    "recommendation_policy",
    "recommendation_semantics_policy",
    "user_policy",
    "planning_policy",
    "library_policy",
    "fusion_policy",
    "version_inventory",
]
