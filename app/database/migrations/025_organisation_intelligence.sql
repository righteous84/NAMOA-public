-- ==========================================================
-- Migration 025
--
-- Sprint 13:
-- Library Organisation Intelligence & Recommendation Foundation
-- ==========================================================
--
-- Schema change rationale (Architect-approved domain model):
--
-- Organisation proposals are a SEPARATE intelligence domain from
-- optimisation recommendations. They share the established
-- Sprint 10 persistence PATTERN (durable row + append-only event
-- ledger + captured intelligence identity) but deliberately do
-- NOT reuse the optimisation `recommendations` table: its shape,
-- analysis-run anchor and CHECKed state vocabulary are
-- optimisation-specific. These tables are genuinely required to
-- make organisation decisions durable, attributable and
-- reconstructable; no table exists "to make a GUI query easier".
--
-- 1. organisation_decision_runs
--    The non-analysis decision anchor for one deterministic
--    proposal-generation execution. It snapshots the exact
--    versioned organisation rule components, the operator policy
--    values (library roots / enabled rules) and the git revision
--    that produced its proposals, plus the derived organisation
--    identity digest. Mirrors configuration_snapshots
--    conventions without touching the ANALYSIS intelligence
--    identity: changing organisation rules must never invalidate
--    analyses.
--
-- 2. organisation_proposals
--    Durable organisation recommendations AS PRODUCED by a
--    decision run: typed intent (move_destination, rename,
--    group_with, flag_duplicate, order_within_group), target
--    media lineage, computed destination/name where meaningful,
--    confidence, risk, rationale lines citing the applied rules,
--    cited evidence (observed facts only; hashes are duplicate
--    evidence, never identity evidence), and the producing
--    run's identity digest. Lifecycle states cover the Sprint 13
--    boundary exactly: 'proposed' -> 'accepted' (durable approved
--    intent recorded; NO filesystem effect) | 'rejected' |
--    'superseded' (supersession derives from newer decision
--    runs). Execution linkage columns belong to Sprint 14 and
--    are intentionally absent.
--
-- 3. organisation_proposal_events
--    Append-only lifecycle ledger over proposals. Rows are never
--    updated or deleted.
--
-- No historical data is backfilled or migrated: organisation
-- history begins with the first Sprint 13 decision run.
-- ==========================================================

CREATE TABLE organisation_decision_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    status TEXT NOT NULL
        CHECK(status IN ('completed', 'failed'))
        DEFAULT 'completed',

    library_roots_json TEXT NOT NULL DEFAULT '[]',

    rule_versions_json TEXT NOT NULL DEFAULT '{}',

    policy_values_json TEXT NOT NULL DEFAULT '{}',

    git_revision TEXT,

    identity_digest TEXT,

    lineages_considered INTEGER NOT NULL DEFAULT 0,

    proposals_created INTEGER NOT NULL DEFAULT 0,

    hash_coverage_total INTEGER NOT NULL DEFAULT 0,

    hash_coverage_hashed INTEGER NOT NULL DEFAULT 0,

    error_message TEXT,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_org_decision_runs_created
    ON organisation_decision_runs (created_at);

CREATE TABLE organisation_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    decision_run_id INTEGER NOT NULL,

    media_id INTEGER NOT NULL,

    related_media_id INTEGER,

    intent TEXT NOT NULL
        CHECK(intent IN (
            'move_destination',
            'rename',
            'group_with',
            'flag_duplicate',
            'order_within_group'
        )),

    proposed_destination TEXT,

    proposed_name TEXT,

    confidence REAL,

    risk TEXT,

    rationale_json TEXT NOT NULL DEFAULT '[]',

    evidence_json TEXT NOT NULL DEFAULT '{}',

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
        REFERENCES organisation_decision_runs(id),

    FOREIGN KEY(media_id)
        REFERENCES media_items(id)
        ON DELETE CASCADE,

    FOREIGN KEY(related_media_id)
        REFERENCES media_items(id)
        ON DELETE SET NULL
);

CREATE INDEX idx_org_proposals_run
    ON organisation_proposals (decision_run_id);

CREATE INDEX idx_org_proposals_media
    ON organisation_proposals (media_id);

CREATE INDEX idx_org_proposals_state
    ON organisation_proposals (state);

CREATE TABLE organisation_proposal_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    proposal_id INTEGER NOT NULL,

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

    FOREIGN KEY(proposal_id)
        REFERENCES organisation_proposals(id)
        ON DELETE CASCADE
);

CREATE INDEX idx_org_proposal_events_proposal
    ON organisation_proposal_events (proposal_id);
