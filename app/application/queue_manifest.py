"""
Sprint 8 operational queue-manifest preparation.

A DERIVED read/serialisation capability over the authoritative
current-valid recommendation reads:

    build_queue_manifest(recommendation_service)

- consumes RecommendationService only (which itself delegates to
  OpportunityQueueService and RecommendationPrioritisationService)
- never reimplements currentness; candidates are current-valid
  because the authorities say so
- contains proposals only: no execution instructions, no FFmpeg
  content, no action plans
- performs NO writes: no database access, no durable queue state,
  no filesystem effects. Serialising the returned dict to a
  caller-chosen destination is the caller's decision (CLI/GUI).
- deterministic: identical authoritative inputs produce an
  identical manifest structure and ordering.
"""

from app.versioning.registry import (
    get_git_revision,
    version_inventory,
)

from app.services.recommendation_prioritisation_service import (
    RecommendationPrioritisationService,
)


MANIFEST_FORMAT = "namoa-queue-manifest"

MANIFEST_VERSION = 1


def _recommendation_entry(item):
    """
    One prioritised recommendation as a plain, ordering-stable dict
    carrying its provenance anchors from the queue authority.
    """

    candidate = item.candidate

    components = item.components

    return {
        "rank": item.rank,
        "media_id": candidate.media_id,
        "file_path": candidate.file_path,
        "file_name": candidate.file_name,
        "opportunity": candidate.opportunity,
        "priority_score": item.priority_score,
        "components": {
            "score_component": components.score_component,
            "confidence_component": (
                components.confidence_component
            ),
            "savings_bytes_component": (
                components.savings_bytes_component
            ),
            "risk_penalty": components.risk_penalty,
            "calibrated_confidence": (
                components.calibrated_confidence
            ),
            "risk_value": components.risk_value,
            "cost_benefit_ratio": components.cost_benefit_ratio,
        },
        "rationale": list(item.rationale),
        "candidate_facts": {
            "opportunity_score": candidate.opportunity_score,
            "confidence": candidate.confidence,
            "estimated_saving_percent": (
                candidate.estimated_saving_percent
            ),
            "file_size_bytes": candidate.file_size_bytes,
            "estimated_saved_bytes": (
                candidate.estimated_saved_bytes
            ),
            "risk": candidate.risk,
        },
        "provenance": {
            "analysis_run_id": candidate.analysis_run_id,
            "observation_id": candidate.observation_id,
        },
    }


def build_queue_manifest(recommendation_service) -> dict:
    """
    Build the reviewable optimisation-proposal manifest from the
    authoritative current-valid prioritised recommendations.
    """

    prioritised = (
        recommendation_service.get_prioritised_recommendations()
    )

    projection = (
        recommendation_service.get_savings_projection()
    )

    return {
        "format": MANIFEST_FORMAT,
        "version": MANIFEST_VERSION,
        "content": "proposals only; non-destructive; derived "
                   "from current-valid opportunities",
        "recommendations": [
            _recommendation_entry(item)
            for item in prioritised
        ],
        "summary": {
            "count": len(prioritised),
            "total_opportunities": (
                projection.total_opportunities
            ),
            "total_size_bytes": projection.total_size_bytes,
            "total_saved_bytes": projection.total_saved_bytes,
            "total_saving_percent": (
                projection.total_saving_percent
            ),
        },
        "attribution": {
            "policy_values": (
                RecommendationPrioritisationService.policy_values()
            ),
            "component_versions": version_inventory(),
            "git_revision": get_git_revision(),
        },
    }
