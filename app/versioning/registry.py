"""
Single source of truth for NAMOA intelligence component semantic versions.

Architectural principle
-----------------------

A semantic change to a versioned intelligence component (its meaning,
calculation, threshold, weighting, classification, confidence behaviour,
or policy constant) MUST change the component's semantic version.

Version identity is part of provenance. A historical analytical result
must never be interpreted using the current version merely because the
component has the same name.

Design
------

- Each versioned component class declares its own `semantic_version`
  class attribute (component declaration). The version string is therefore
  co-located with the code that defines the semantics, which makes it
  obvious to a future developer that changing semantics requires bumping
  the version.
- This module is the single collector point. It reads versions from the
  component classes and assembles a run-level manifest, rather than
  maintaining a second hard-coded version registry that could drift from
  the code.

Version representation: semantic versioning "MAJOR.MINOR.PATCH".
A semantic (meaning-changing) change requires at least a MINOR bump; a
breaking semantic change requires a MAJOR bump.
"""

from pathlib import Path
import hashlib
import json
import subprocess

from app.experts.classification_expert import ClassificationExpert
from app.experts.codec_expert import CodecExpert
from app.experts.audio_expert import AudioExpert
from app.experts.resolution_expert import ResolutionExpert
from app.experts.hdr_expert import HDRExpert
from app.experts.container_expert import ContainerExpert
from app.experts.source_expert import SourceExpert
from app.experts.quality_expert import QualityExpert

from app.decision_engine.decision_engine import DecisionEngine
from app.decision_engine.fusion_engine.fusion_engine import FusionEngine
from app.decision_engine.fusion_engine.recommendation_decision_weights import (
    RULE_WEIGHTS,
)
from app.decision_engine.rules.codec_rule import CodecRule
from app.decision_engine.rules.bitrate_rule import BitrateRule
from app.decision_engine.rules.resolution_rule import ResolutionRule
from app.decision_engine.rules.hdr_rule import HDRRule
from app.decision_engine.rules.container_rule import ContainerRule
from app.decision_engine.rules.source_rule import SourceRule
from app.decision_engine.rules.audio_rule import AudioRule

from app.services.recommendation_prioritisation_service import (
    RecommendationPrioritisationService,
)
from app.services.recommendation_semantics_service import (
    RecommendationSemanticsService,
)
from app.services.savings_conversion import SavingsConversion
from app.services.library_intelligence_service import (
    LibraryIntelligenceService,
)
from app.models.user_policy import UserPolicy, USER_POLICY_VERSION

from app.execution.planning import (
    EncodingSpeedPolicy,
    PLANNING_POLICY_VERSION,
)

# The aggregate pipeline semantic version. Bump when the overall
# analysis pipeline semantics change.
#
# 2.0.0: the intelligence relationship work. Decision Rules now
# evaluate combined relationships (codec/bitrate/resolution/source/
# audio/container/size/knowledge/policy) rather than independent
# numeric bands; Fusion reconciles signals by proposition, suppresses
# contradicted opportunities, separates value from confidence, and
# classifies opportunity levels; user policy is a first-class
# decision input; recommendations are human-readable interpretations.
# 2.1.0: focused correction. Rules fail closed in production when
# required Knowledge is missing (no silent untracked fallback);
# planning/cost semantics for the encoding-speed preference are
# established and versioned (planning_policy); user policy and
# planning semantics remain separate from factual intelligence.
# 2.2.0: Phase 8 transformation-aware savings semantics. Fusion no
# longer derives an estimated saving percentage from the opportunity
# score (`score * 50`); assessment savings come from the actual
# proposed transformation's evidence. Compatibility-only propositions
# carry no fabricated storage saving.
PIPELINE_VERSION = "2.2.0"

GIT_UNAVAILABLE = "unavailable"

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# The authoritative set of versioned intelligence component classes.
VERSIONED_EXPERTS = (
    ClassificationExpert,
    CodecExpert,
    AudioExpert,
    ResolutionExpert,
    HDRExpert,
    ContainerExpert,
    SourceExpert,
    QualityExpert,
)

VERSIONED_RULES = (
    CodecRule,
    BitrateRule,
    ResolutionRule,
    HDRRule,
    ContainerRule,
    SourceRule,
    AudioRule,
)


def version_inventory() -> dict:
    """
    Authoritative, inspectable inventory of all versioned intelligence
    components.

    Returns a dict keyed by component name with its category, current
    semantic version, and whether policy/configuration values affect its
    semantics. This does not require pipeline instances and is the
    canonical record of what is versioned.
    """

    inventory = {}

    for expert in VERSIONED_EXPERTS:
        inventory[expert.name] = {
            "category": "expert",
            "version": expert.semantic_version,
            "policy_affecting": False,
        }

    for rule in VERSIONED_RULES:
        inventory[rule.name] = {
            "category": "decision_rule",
            "version": rule.semantic_version,
            "policy_affecting": False,
        }

    inventory["decision_engine"] = {
        "category": "decision_engine",
        "version": DecisionEngine.semantic_version,
        "policy_affecting": False,
    }

    inventory["fusion_engine"] = {
        "category": "fusion_engine",
        "version": FusionEngine.semantic_version,
        "policy_affecting": True,
    }

    inventory["recommendation_policy"] = {
        "category": "recommendation_policy",
        "version": (
            RecommendationPrioritisationService.semantic_version
        ),
        "policy_affecting": True,
    }

    inventory["recommendation_semantics"] = {
        "category": "recommendation_semantics",
        "version": (
            RecommendationSemanticsService.semantic_version
        ),
        "policy_affecting": True,
    }

    inventory["user_policy"] = {
        "category": "user_policy",
        "version": USER_POLICY_VERSION,
        "policy_affecting": True,
    }

    inventory["planning_policy"] = {
        "category": "planning_policy",
        "version": PLANNING_POLICY_VERSION,
        "policy_affecting": True,
    }

    inventory["library_policy"] = {
        "category": "library_policy",
        "version": LibraryIntelligenceService.semantic_version,
        "policy_affecting": True,
    }

    # Phase 9 per-transformation expected-outcome conversion. The
    # conversion takes no policy input. It is collected here for
    # attribution; it is deliberately NOT added to the run-level
    # component manifest, whose digest drives analysis reuse:
    # relocation is byte-identical by construction, so existing
    # analyses keep their meaning and must not be invalidated.
    # Per-assessment attribution travels in signal evidence
    # (basis/modelling_version).
    inventory["savings_conversion"] = {
        "category": "savings_conversion",
        "version": SavingsConversion.semantic_version,
        "policy_affecting": False,
    }

    return inventory


def get_git_revision() -> str:
    """
    Return the short HEAD revision of the repository, or GIT_UNAVAILABLE.

    The Git revision identifies the concrete code revision that executed.
    It complements (never replaces) the semantic component versions.

    Behaviour when Git is unavailable: returns GIT_UNAVAILABLE, and normal
    analysis is not blocked. A dirty working tree is not distinguished:
    the HEAD revision identifies the committed code that executed;
    uncommitted changes are not separately captured by this helper.
    """

    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(_PROJECT_ROOT),
                "rev-parse",
                "--short",
                "HEAD",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )

        revision = result.stdout.strip()

        if result.returncode == 0 and revision:
            return revision

    except Exception:
        pass

    return GIT_UNAVAILABLE


def build_component_versions(expert_manager, decision_engine) -> dict:
    """
    Assemble the semantic version manifest from the components actually
    used by an analysis run.
    """

    return {
        "pipeline": PIPELINE_VERSION,
        "experts": {
            expert.name: expert.semantic_version
            for expert in expert_manager.experts
        },
        "decision_rules": {
            rule.name: rule.semantic_version
            for rule in decision_engine.rules
        },
        "decision_engine": decision_engine.semantic_version,
        "fusion_engine": decision_engine.fusion.semantic_version,
        "recommendation_policy": (
            RecommendationPrioritisationService.semantic_version
        ),
        "recommendation_semantics": (
            RecommendationSemanticsService.semantic_version
        ),
        "user_policy": USER_POLICY_VERSION,
        "planning_policy": PLANNING_POLICY_VERSION,
        "library_policy": (
            LibraryIntelligenceService.semantic_version
        ),
    }


def fusion_policy() -> dict:
    """
    Fusion policy values that affect analytical meaning.
    """

    return {
        "rule_weights": RULE_WEIGHTS,
        "confidence_cap": FusionEngine.CONFIDENCE_CAP,
    }


def recommendation_policy() -> dict:
    """
    Recommendation / prioritisation policy values that affect meaning.
    """

    return {
        "version": RecommendationPrioritisationService.semantic_version,
        "policy": RecommendationPrioritisationService.policy_values(),
    }


def recommendation_semantics_policy() -> dict:
    """
    Recommendation-narrative semantics policy values that affect
    meaning.
    """

    return {
        "version": RecommendationSemanticsService.semantic_version,
    }


def user_policy(policy=None) -> dict:
    """
    The user policy values that affect decision meaning.

    `policy` may supply the active UserPolicy (for example a caller
    that parameterises a run); when omitted the standard default
    applies.
    """

    return (
        policy if policy is not None else UserPolicy.default()
    ).to_policy_payload()


def planning_policy() -> dict:
    """
    The planning/cost semantics policy values that affect meaning
    (encoding-speed preference interpretation).
    """

    return EncodingSpeedPolicy.policy_values()


def library_policy() -> dict:
    """
    Library intelligence policy values that affect meaning.
    """

    return {
        "version": LibraryIntelligenceService.semantic_version,
        "policy": LibraryIntelligenceService.policy_values(),
    }


def build_policy_values(user_policy_obj=None) -> dict:
    """
    Assemble the configuration/policy values attributable to a run.

    `user_policy_obj` may supply the active UserPolicy so the identity
    reflects the policy actually used; when omitted the standard
    default applies.
    """

    return {
        "fusion": fusion_policy(),
        "recommendation": recommendation_policy(),
        "recommendation_semantics": recommendation_semantics_policy(),
        "user_policy": user_policy(user_policy_obj),
        "planning": planning_policy(),
        "library": library_policy(),
        "evidence": evidence_weight_policy(),
    }


def evidence_weight_policy() -> dict:
    """
    The ACTIVE evidence-source weighting policy that influenced
    classification. Placeholder/reserved sources are represented only
    by name so they are never mistaken for active intelligence.
    """

    from app.services.evidence_weight_service import (
        EvidenceWeightService,
    )

    return EvidenceWeightService().active_policy()


# ----------------------------------------------------------------------
# Canonical intelligence identity
# ----------------------------------------------------------------------
#
# The identity is the deterministic digest of every intelligence-
# affecting input that a run's meaning depends on, assembled from the
# SAME manifest and policy payloads that are persisted verbatim in the
# run's configuration snapshot.
#
# Deliberately EXCLUDED from the identity (irrelevant runtime/software
# changes must not invalidate analyses):
#
#   - the git revision (implementation detail)
#   - anything not declared above
#
# Knowledge sets participate at set-version granularity through the
# knowledge_versions mapping supplied by the caller (the sets actually
# consulted by the run being attributed, or being compared).


def canonical_intelligence_identity(
    component_versions: dict,
    policy_values: dict,
    knowledge_versions: dict | None = None,
) -> dict:
    """
    Build the canonical intelligence identity payload.

    knowledge_versions maps knowledge-set name to the set version that
    was resolved for this context.
    """

    payload = {
        "schema": "namoa-intelligence-identity/1",
        "component_versions": component_versions,
        "policy_values": policy_values,
        "knowledge_versions": dict(
            sorted(
                (knowledge_versions or {}).items()
            )
        ),
    }

    return payload


def intelligence_identity_digest(
    component_versions: dict,
    policy_values: dict,
    knowledge_versions: dict | None = None,
) -> str:
    """
    Deterministic sha256 hex digest of the canonical intelligence
    identity payload. Equal inputs always produce an equal digest;
    any relevant intelligence change produces a different one.
    """

    payload = canonical_intelligence_identity(
        component_versions,
        policy_values,
        knowledge_versions,
    )

    canonical_json = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical_json.encode("utf-8")
    ).hexdigest()
