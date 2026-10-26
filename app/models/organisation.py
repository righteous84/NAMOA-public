"""Organisation domain persistence read models (Sprint 13).

The organisation proposal lifecycle mirrors the established
recommendation-record pattern (durable rows, validated
transitions, append-only events) as a SEPARATE intelligence
domain. Sprint 13 ends before filesystem mutation: 'accepted'
records the durable approved intent only; execution linkage is
owned by Sprint 14 and is intentionally not modelled here.
"""

from dataclasses import dataclass, field
from typing import Optional


# Lifecycle states (Sprint 13 boundary).
STATE_PROPOSED = "proposed"
STATE_ACCEPTED = "accepted"
STATE_REJECTED = "rejected"
STATE_SUPERSEDED = "superseded"

TERMINAL_STATES = frozenset(
    {STATE_REJECTED, STATE_SUPERSEDED}
)

ALLOWED_TRANSITIONS = {
    STATE_PROPOSED: {
        STATE_PROPOSED,
        STATE_ACCEPTED,
        STATE_REJECTED,
        STATE_SUPERSEDED,
    },
    # Accepted proposals record a durable human decision. The
    # execution-side lifecycle that will consume this intent
    # belongs to Sprint 14; no further Sprint 13 transition
    # exists.
    STATE_ACCEPTED: {STATE_ACCEPTED},
    STATE_REJECTED: {STATE_REJECTED},
    STATE_SUPERSEDED: {STATE_SUPERSEDED},
}

# Typed proposal intents. Each intent is a distinct structured
# meaning; they are never conflated with each other or with
# optimisation opportunities.
INTENT_MOVE_DESTINATION = "move_destination"
INTENT_RENAME = "rename"
INTENT_GROUP_WITH = "group_with"
INTENT_FLAG_DUPLICATE = "flag_duplicate"
INTENT_ORDER_WITHIN_GROUP = "order_within_group"

INTENTS = (
    INTENT_MOVE_DESTINATION,
    INTENT_RENAME,
    INTENT_GROUP_WITH,
    INTENT_FLAG_DUPLICATE,
    INTENT_ORDER_WITHIN_GROUP,
)


def assert_transition(current: str, new: str) -> None:

    allowed = ALLOWED_TRANSITIONS.get(current)

    if allowed is None:
        raise ValueError(
            f"unknown organisation proposal state "
            f"'{current}'"
        )

    if new not in allowed:
        raise ValueError(
            f"illegal organisation proposal state "
            f"transition '{current}' -> '{new}'"
        )


@dataclass(slots=True)
class OrganisationDecisionRunRecord:
    """
    Read model of one organisation decision run anchor.

    The snapshot fields preserve exactly the rule versions,
    policy values and digest that produced the run's proposals.
    """

    id: int

    status: str = "completed"

    library_roots: list = field(default_factory=list)

    rule_versions: dict = field(default_factory=dict)

    policy_values: dict = field(default_factory=dict)

    git_revision: Optional[str] = None

    identity_digest: Optional[str] = None

    lineages_considered: int = 0

    proposals_created: int = 0

    hash_coverage_total: int = 0

    hash_coverage_hashed: int = 0

    error_message: Optional[str] = None

    created_at: Optional[str] = None

    # Sprint 15 optional anchors (nullable columns; older
    # rows read as None/empty).
    profile_id: Optional[int] = None

    profile_digest: Optional[str] = None

    metadata_fingerprint: Optional[str] = None

    mutation_strategy: Optional[str] = None

    operation_count: Optional[int] = None

    strategy_reasoning: list = field(default_factory=list)


@dataclass(slots=True)
class OrganisationProposalRecord:
    """
    Read model of one durable organisation proposal AS PRODUCED
    BY ITS DECISION RUN. Nothing is re-derived from current
    rules when reading.
    """

    id: int

    decision_run_id: int

    media_id: int

    intent: str

    related_media_id: Optional[int] = None

    proposed_destination: Optional[str] = None

    proposed_name: Optional[str] = None

    confidence: Optional[float] = None

    risk: Optional[str] = None

    rationale: list = field(default_factory=list)

    evidence: dict = field(default_factory=dict)

    intelligence_identity: Optional[str] = None

    state: str = STATE_PROPOSED

    created_at: Optional[str] = None

    updated_at: Optional[str] = None


# ---------------------------------------------------------
# Sprint 15 records
# ---------------------------------------------------------

# Scope-action lifecycle mirrors the proposal lifecycle at
# scope grain: 'accepted' records durable approved intent
# for one structural action; filesystem effect belongs
# exclusively to the execution authority.
SCOPE_ACTION_STATES = frozenset(
    {
        STATE_PROPOSED,
        STATE_ACCEPTED,
        STATE_REJECTED,
        STATE_SUPERSEDED,
    }
)

# Structural action types (closed set, Sprint 15).
SCOPE_ACTION_DIRECTORY_RENAME = "directory_rename"
SCOPE_ACTION_DIRECTORY_MOVE = "directory_move"
SCOPE_ACTION_SUBTREE_RELOCATION = "subtree_relocation"
SCOPE_ACTION_DIRECTORY_CREATION = "directory_creation"
SCOPE_ACTION_FILE_RENAME = "file_rename"
SCOPE_ACTION_FILE_MOVE = "file_move"
SCOPE_ACTION_COMBINATION = "combination"
SCOPE_ACTION_NO_MUTATION = "no_mutation"

SCOPE_ACTION_TYPES = frozenset(
    {
        SCOPE_ACTION_DIRECTORY_RENAME,
        SCOPE_ACTION_DIRECTORY_MOVE,
        SCOPE_ACTION_SUBTREE_RELOCATION,
        SCOPE_ACTION_DIRECTORY_CREATION,
        SCOPE_ACTION_FILE_RENAME,
        SCOPE_ACTION_FILE_MOVE,
        SCOPE_ACTION_COMBINATION,
        SCOPE_ACTION_NO_MUTATION,
    }
)


@dataclass(slots=True)
class OrganisationScopeActionRecord:
    """
    Read model of one durable scope-level (structural)
    action AS PRODUCED BY ITS DECISION RUN. Scope grain:
    one row covers a directory/subtree operation with a
    descendant manifest, never a single file. Nothing is
    re-derived when reading.
    """

    id: int

    decision_run_id: int

    scope_path: str = ""

    action_type: str = SCOPE_ACTION_NO_MUTATION

    source_path: str = ""

    destination_path: str = ""

    descendant_manifest: list = field(default_factory=list)

    strategy: str = ""

    operation_count: int = 0

    reasoning: list = field(default_factory=list)

    review_conditions: list = field(default_factory=list)

    descendant_proposal_ids: list = field(
        default_factory=list
    )

    intelligence_identity: Optional[str] = None

    state: str = STATE_PROPOSED

    created_at: Optional[str] = None

    updated_at: Optional[str] = None


@dataclass(slots=True)
class OrganisationScopeExecutionRecord:
    """
    Read model of one durable scope-execution lifecycle
    record. Operated by the same OrganisationExecutionService
    authority with the same lifecycle vocabulary as
    per-file executions; grain is one scope action rather
    than one file. Per-descendant observations reuse the
    existing file_observations and continuity tables.
    """

    id: int

    scope_action_id: int

    decision_run_id: int

    action_type: str = SCOPE_ACTION_NO_MUTATION

    source_path: str = ""

    destination_path: str = ""

    descendant_manifest: list = field(default_factory=list)

    state: str = STATE_PROPOSED

    error: Optional[str] = None

    descendants_completed: list = field(
        default_factory=list
    )

    actor: str = "human"

    created_at: Optional[str] = None

    updated_at: Optional[str] = None


@dataclass(slots=True)
class MetadataObservationRecord:
    """
    Read model of one immutable provider metadata snapshot
    row. Rows are never updated; re-fetches append. Payload
    carries the relevant-values subset only and must never
    contain credential values.
    """

    id: int

    media_id: int

    provider: str = ""

    provider_item_id: str = ""

    provider_item_kind: str = ""

    retrieved_at: Optional[str] = None

    source_fingerprint: str = ""

    association_strength: str = ""

    association_basis: str = ""

    payload: dict = field(default_factory=dict)

    created_at: Optional[str] = None


@dataclass(slots=True)
class OrganisationProfileRecord:
    """
    Read model of one saved organisation profile: a
    single current configuration, not a version. The
    unique name is the identity; editing updates the
    row in place. Decision runs cite profile id plus
    digest.
    """

    id: int

    name: str = ""

    payload: dict = field(default_factory=dict)

    digest: str = ""

    created_at: Optional[str] = None

    updated_at: Optional[str] = None


@dataclass(slots=True)
class IntegrationSettingsRecord:
    """
    Read model of one provider integration settings row.
    Non-secret configuration only; credential values live
    exclusively in the platform secret store or the
    documented environment override, never here.
    """

    id: int

    provider: str = ""

    enabled: bool = False

    base_url: str = ""

    jellyfin_user_id: Optional[str] = None

    secret_ref: str = ""

    created_at: Optional[str] = None

    updated_at: Optional[str] = None
