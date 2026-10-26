-- ==========================================================
-- Migration 036
--
-- Sprint 15:
-- Metadata-Aware Library Organisation & Reconciliation
-- ==========================================================
--
-- Schema change rationale (Architect-approved domain model):
--
-- Sprint 15 adds provider-backed organisation planning while
-- preserving every existing boundary. External provider
-- metadata is dynamic evidence, so it is stored as immutable
-- observation rows with source fingerprints rather than as
-- versioned application semantics. Operator-owned organisation
-- profiles are append-only versioned configuration snapshotted
-- into decision runs. Structural (scope-level) actions are a
-- separate persistence grain from per-file proposals, so they
-- get their own action and execution tables reusing the
-- established durable-row plus append-only-ledger pattern;
-- the existing proposal intent CHECK and the existing
-- per-file execution tables are deliberately untouched.
--
-- 1. metadata_observations
--    Immutable per-retrieval provider metadata snapshots:
--    which provider and item, when acquired, the source
--    fingerprint over the normalised relevant payload, the
--    association strength/basis for the linked lineage, and
--    the relevant-values subset actually used. Rows are never
--    updated; re-fetches append new rows. No secrets: payloads
--    must never contain credential values.
--
-- 2. organisation_profiles
--    Append-only organisation profile versions: name, payload
--    (roots, movie/TV/category templates, category folders,
--    intelligent category rule toggles/thresholds, explicit
--    tag mappings with precedence, naming components,
--    collision policy), canonical digest, timestamps.
--    Decision runs reference a profile id; historical rows are
--    never rewritten.
--
-- 3. integration_settings
--    Non-secret per-provider integration configuration: one
--    row per provider (jellyfin/radarr/sonarr), enabled flag,
--    base URL, Jellyfin user id, secret-store key reference
--    name only. No secret columns by design; credential values
--    live exclusively in the platform secret store or the
--    documented environment override.
--
-- 4. organisation_scope_actions
--    Durable scope-level (structural) actions AS PRODUCED by a
--    decision run: scope path, action type, source,
--    destination, descendant manifest, selected mutation
--    strategy, operation count, reasoning, review conditions.
--    Lifecycle mirrors proposals (proposed/accepted/rejected/
--    superseded) with an append-only event ledger. Approving a
--    scope action transitions its covered descendant
--    per-file proposals together, atomically, with per-item
--    events preserved.
--
-- 5. organisation_scope_executions (+ events)
--    Durable lifecycle records for approved scope actions,
--    operated by the same OrganisationExecutionService
--    authority with the same lifecycle vocabulary as
--    per-file executions. Per-descendant observations reuse
--    the existing file_observations and continuity tables.
--
-- 6. organisation_decision_runs additions
--    Nullable, backward-compatible columns only: profile id
--    and digest, metadata fingerprint roll-up, selected
--    mutation strategy, operation count, strategy reasoning.
--    Existing rows stay NULL-valid; existing readers are
--    unaffected.
--
-- No historical data is backfilled or migrated.
-- ==========================================================

CREATE TABLE metadata_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    media_id INTEGER NOT NULL,

    provider TEXT NOT NULL
        CHECK(provider IN (
            'jellyfin',
            'radarr',
            'sonarr'
        )),

    provider_item_id TEXT NOT NULL,

    provider_item_kind TEXT NOT NULL
        CHECK(provider_item_kind IN (
            'movie',
            'series',
            'season',
            'episode',
            'file'
        )),

    retrieved_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    source_fingerprint TEXT NOT NULL,

    association_strength TEXT NOT NULL
        CHECK(association_strength IN (
            'exact_path',
            'cross_provider_id',
            'single_id_title',
            'fuzzy_ambiguous'
        )),

    association_basis TEXT NOT NULL DEFAULT '',

    payload_json TEXT NOT NULL DEFAULT '{}',

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(media_id)
        REFERENCES media_items(id)
        ON DELETE CASCADE,

    UNIQUE(
        media_id,
        provider,
        provider_item_id,
        source_fingerprint
    )
);

CREATE INDEX idx_metadata_observations_media
    ON metadata_observations (media_id);

CREATE INDEX idx_metadata_observations_provider_item
    ON metadata_observations (provider, provider_item_id);

CREATE TABLE organisation_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    name TEXT NOT NULL,

    version INTEGER NOT NULL DEFAULT 1,

    payload_json TEXT NOT NULL DEFAULT '{}',

    digest TEXT NOT NULL DEFAULT '',

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_organisation_profiles_name
    ON organisation_profiles (name);

CREATE TABLE integration_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    provider TEXT NOT NULL UNIQUE
        CHECK(provider IN (
            'jellyfin',
            'radarr',
            'sonarr'
        )),

    enabled INTEGER NOT NULL DEFAULT 0,

    base_url TEXT NOT NULL DEFAULT '',

    jellyfin_user_id TEXT,

    secret_ref TEXT NOT NULL DEFAULT '',

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE organisation_scope_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    decision_run_id INTEGER NOT NULL,

    scope_path TEXT NOT NULL,

    action_type TEXT NOT NULL
        CHECK(action_type IN (
            'directory_rename',
            'directory_move',
            'subtree_relocation',
            'directory_creation',
            'file_rename',
            'file_move',
            'combination',
            'no_mutation'
        )),

    source_path TEXT NOT NULL,

    destination_path TEXT NOT NULL,

    descendant_manifest_json TEXT NOT NULL DEFAULT '[]',

    strategy TEXT NOT NULL DEFAULT '',

    operation_count INTEGER NOT NULL DEFAULT 0,

    reasoning_json TEXT NOT NULL DEFAULT '[]',

    review_conditions_json TEXT NOT NULL DEFAULT '[]',

    descendant_proposal_ids_json TEXT NOT NULL DEFAULT '[]',

    intelligence_identity TEXT,

    state TEXT NOT NULL DEFAULT 'proposed'
        CHECK(state IN (
            'proposed',
            'accepted',
            'rejected',
            'superseded'
        )),

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(decision_run_id)
        REFERENCES organisation_decision_runs(id)
);

CREATE INDEX idx_org_scope_actions_run
    ON organisation_scope_actions (decision_run_id);

CREATE INDEX idx_org_scope_actions_state
    ON organisation_scope_actions (state);

CREATE TABLE organisation_scope_action_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    scope_action_id INTEGER NOT NULL,

    event_type TEXT NOT NULL
        CHECK(event_type IN (
            'proposed',
            'accepted',
            'rejected',
            'superseded'
        )),

    previous_state TEXT,

    new_state TEXT,

    actor TEXT NOT NULL DEFAULT 'system',

    detail TEXT,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(scope_action_id)
        REFERENCES organisation_scope_actions(id)
        ON DELETE CASCADE
);

CREATE TABLE organisation_scope_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    scope_action_id INTEGER NOT NULL UNIQUE,

    decision_run_id INTEGER NOT NULL,

    action_type TEXT NOT NULL,

    source_path TEXT NOT NULL,

    destination_path TEXT NOT NULL,

    descendant_manifest_json TEXT NOT NULL DEFAULT '[]',

    state TEXT NOT NULL DEFAULT 'proposed'
        CHECK(state IN (
            'proposed',
            'approved',
            'precondition_verified',
            'executing',
            'verifying',
            'observation_persistence',
            'provenance_persistence',
            'succeeded',
            'failed',
            'interrupted',
            'recovery_required'
        )),

    error TEXT,

    descendants_completed_json TEXT NOT NULL DEFAULT '[]',

    actor TEXT NOT NULL DEFAULT 'human',

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(scope_action_id)
        REFERENCES organisation_scope_actions(id),

    FOREIGN KEY(decision_run_id)
        REFERENCES organisation_decision_runs(id)
);

CREATE INDEX idx_org_scope_executions_action
    ON organisation_scope_executions (scope_action_id);

CREATE INDEX idx_org_scope_executions_state
    ON organisation_scope_executions (state);

CREATE TABLE organisation_scope_execution_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    scope_execution_id INTEGER NOT NULL,

    event_type TEXT NOT NULL,

    previous_state TEXT,

    new_state TEXT,

    actor TEXT NOT NULL DEFAULT 'system',

    detail TEXT,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(scope_execution_id)
        REFERENCES organisation_scope_executions(id)
        ON DELETE CASCADE
);

ALTER TABLE organisation_decision_runs
    ADD COLUMN profile_id INTEGER;

ALTER TABLE organisation_decision_runs
    ADD COLUMN profile_digest TEXT;

ALTER TABLE organisation_decision_runs
    ADD COLUMN metadata_fingerprint TEXT;

ALTER TABLE organisation_decision_runs
    ADD COLUMN mutation_strategy TEXT;

ALTER TABLE organisation_decision_runs
    ADD COLUMN operation_count INTEGER;

ALTER TABLE organisation_decision_runs
    ADD COLUMN strategy_reasoning_json TEXT NOT NULL DEFAULT '[]';

-- 7. organisation_scope_claims
--    The authoritative concurrency boundary for scope
--    executions, mirroring organisation_execution_scopes
--    at scope grain: path UNIQUE serialises conflicting
--    structural operations. Held from EXECUTING until a
--    terminal state, then released. Rows are management
--    records, not analytical history.
--
-- 8. organisation_scope_continuity
--    Execution-authorised identity continuity for scope
--    executions, mirroring
--    organisation_execution_continuity at scope grain:
--    one row per affected descendant linking its source
--    observation to its resulting observation, naming the
--    scope execution as authority. Per-file continuity
--    rows keep every descendant independently
--    attributable; normal scanning never creates them.

CREATE TABLE organisation_scope_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    scope_execution_id INTEGER NOT NULL,

    path TEXT NOT NULL,

    role TEXT NOT NULL
        CHECK(role IN ('source', 'destination')),

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(path),

    FOREIGN KEY(scope_execution_id)
        REFERENCES organisation_scope_executions(id)
        ON DELETE CASCADE
);

CREATE TABLE organisation_scope_continuity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    scope_execution_id INTEGER NOT NULL,

    media_id INTEGER NOT NULL,

    source_observation_id INTEGER NOT NULL,

    result_observation_id INTEGER NOT NULL,

    authority TEXT NOT NULL DEFAULT 'organisation_scope_execution',

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(scope_execution_id)
        REFERENCES organisation_scope_executions(id)
        ON DELETE CASCADE,

    FOREIGN KEY(media_id)
        REFERENCES media_items(id)
        ON DELETE CASCADE,

    FOREIGN KEY(source_observation_id)
        REFERENCES file_observations(id),

    FOREIGN KEY(result_observation_id)
        REFERENCES file_observations(id)
);

CREATE INDEX idx_org_scope_continuity_execution
    ON organisation_scope_continuity (scope_execution_id);

CREATE INDEX idx_org_scope_continuity_media
    ON organisation_scope_continuity (media_id);
