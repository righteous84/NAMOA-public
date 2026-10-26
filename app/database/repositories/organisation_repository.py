"""
Organisation proposal persistence (Sprint 13).

Thin repository over the organisation_decision_runs /
organisation_proposals / organisation_proposal_events tables
(migration 025). Rows are durable historical results of
organisation decision runs:

- created by the OrganisationIntelligenceService when a
  decision run completes, in state 'proposed'
- evolved ONLY through validated lifecycle transitions, each of
  which appends an immutable event row
- never deleted; newer proposals never rewrite older ones

This is a SEPARATE intelligence domain from the optimisation
recommendation records; it deliberately shares only the
established persistence PATTERN, not the optimisation tables or
authorities.

Commit conventions mirror RecommendationRepository: lifecycle
transitions commit themselves (human decisions are durable);
creation paths leave the transaction to the caller so a whole
decision run can be committed as one atomic unit.
"""

import json

from app.models.organisation import (
    IntegrationSettingsRecord,
    MetadataObservationRecord,
    OrganisationDecisionRunRecord,
    OrganisationProposalRecord,
    OrganisationProfileRecord,
    OrganisationScopeActionRecord,
    OrganisationScopeExecutionRecord,
    assert_transition,
)


class OrganisationError(ValueError):
    """Raised for illegal organisation lifecycle operations."""


class OrganisationRepository:

    def __init__(self, connection):

        self.connection = connection

    # ---------------------------------------------------------
    # decision runs
    # ---------------------------------------------------------

    def create_decision_run(
        self,
        *,
        library_roots: list,
        rule_versions: dict,
        policy_values: dict,
        git_revision: str | None,
        identity_digest: str | None,
        lineages_considered: int,
        proposals_created: int,
        hash_coverage_total: int,
        hash_coverage_hashed: int,
        profile_id: int | None = None,
        profile_digest: str | None = None,
        metadata_fingerprint: str | None = None,
        mutation_strategy: str | None = None,
        operation_count: int | None = None,
        strategy_reasoning: list | None = None,
    ) -> int:
        """
        Anchor one completed decision run. Called last within
        the generation transaction, after all payloads exist in
        memory, so a run is visible only when complete.

        Sprint 15 anchors are optional and backward
        compatible: on databases without migration 036 the
        extra columns do not exist, so they are written
        only when the schema supports them.
        """

        cursor = self.connection.cursor()

        if self._has_sprint15_run_columns(cursor):
            cursor.execute(
                """
                INSERT INTO organisation_decision_runs (
                    status,
                    library_roots_json,
                    rule_versions_json,
                    policy_values_json,
                    git_revision,
                    identity_digest,
                    lineages_considered,
                    proposals_created,
                    hash_coverage_total,
                    hash_coverage_hashed,
                    profile_id,
                    profile_digest,
                    metadata_fingerprint,
                    mutation_strategy,
                    operation_count,
                    strategy_reasoning_json
                )
                VALUES (
                    'completed', ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    json.dumps(list(library_roots)),
                    json.dumps(dict(rule_versions)),
                    json.dumps(dict(policy_values)),
                    git_revision,
                    identity_digest,
                    lineages_considered,
                    proposals_created,
                    hash_coverage_total,
                    hash_coverage_hashed,
                    profile_id,
                    profile_digest,
                    metadata_fingerprint,
                    mutation_strategy,
                    operation_count,
                    json.dumps(list(strategy_reasoning or [])),
                ),
            )
        else:
            cursor.execute(
                """
                INSERT INTO organisation_decision_runs (
                    status,
                    library_roots_json,
                    rule_versions_json,
                    policy_values_json,
                    git_revision,
                    identity_digest,
                    lineages_considered,
                    proposals_created,
                    hash_coverage_total,
                    hash_coverage_hashed
                )
                VALUES (
                    'completed', ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    json.dumps(list(library_roots)),
                    json.dumps(dict(rule_versions)),
                    json.dumps(dict(policy_values)),
                    git_revision,
                    identity_digest,
                    lineages_considered,
                    proposals_created,
                    hash_coverage_total,
                    hash_coverage_hashed,
                ),
            )

        return cursor.lastrowid

    @staticmethod
    def _has_sprint15_run_columns(cursor) -> bool:
        try:
            names = {
                row[1]
                for row in cursor.execute(
                    "PRAGMA table_info("
                    "organisation_decision_runs)"
                ).fetchall()
            }
        except Exception:
            return False

        return {
            "profile_id",
            "profile_digest",
            "metadata_fingerprint",
            "mutation_strategy",
            "operation_count",
            "strategy_reasoning_json",
        } <= names

    def get_decision_run(
        self,
        decision_run_id: int,
    ) -> OrganisationDecisionRunRecord | None:

        row = self.connection.execute(
            """
            SELECT *
            FROM organisation_decision_runs
            WHERE id = ?
            """,
            (decision_run_id,),
        ).fetchone()

        if row is None:
            return None

        return self._decision_run_from_row(row)

    def latest_decision_run(
        self,
    ) -> OrganisationDecisionRunRecord | None:

        row = self.connection.execute(
            """
            SELECT *
            FROM organisation_decision_runs
            ORDER BY id DESC
            LIMIT 1
            """,
        ).fetchone()

        if row is None:
            return None

        return self._decision_run_from_row(row)

    def list_decision_runs(
        self,
    ) -> list[OrganisationDecisionRunRecord]:

        rows = self.connection.execute(
            """
            SELECT *
            FROM organisation_decision_runs
            ORDER BY id DESC
            """
        ).fetchall()

        return [
            self._decision_run_from_row(row)
            for row in rows
        ]

    # ---------------------------------------------------------
    # proposals
    # ---------------------------------------------------------

    def create_proposed(
        self,
        *,
        decision_run_id: int,
        media_id: int,
        intent: str,
        related_media_id: int | None,
        proposed_destination: str | None,
        proposed_name: str | None,
        confidence: float | None,
        risk: str | None,
        rationale: list,
        evidence: dict,
        intelligence_identity: str | None,
    ) -> int:
        """
        Persist one proposal AS PRODUCED BY ITS DECISION RUN in
        state 'proposed', recording the 'proposed' lifecycle
        event. No commit: the caller commits the whole decision
        run atomically.
        """

        cursor = self.connection.cursor()

        cursor.execute(
            """
            INSERT INTO organisation_proposals (
                decision_run_id,
                media_id,
                related_media_id,
                intent,
                proposed_destination,
                proposed_name,
                confidence,
                risk,
                rationale_json,
                evidence_json,
                intelligence_identity,
                state
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    'proposed')
            """,
            (
                decision_run_id,
                media_id,
                related_media_id,
                intent,
                proposed_destination,
                proposed_name,
                confidence,
                risk,
                json.dumps(list(rationale or [])),
                json.dumps(dict(evidence or {})),
                intelligence_identity,
            ),
        )

        proposal_id = cursor.lastrowid

        self._record_event(
            cursor,
            proposal_id=proposal_id,
            event_type="proposed",
            previous_state=None,
            new_state="proposed",
            actor="organisation_intelligence",
            detail=None,
        )

        return proposal_id

    def get_proposal(
        self,
        proposal_id: int,
    ) -> OrganisationProposalRecord | None:

        row = self.connection.execute(
            """
            SELECT *
            FROM organisation_proposals
            WHERE id = ?
            """,
            (proposal_id,),
        ).fetchone()

        if row is None:
            return None

        return self._proposal_from_row(row)

    def list_by_decision_run(
        self,
        decision_run_id: int,
    ) -> list[OrganisationProposalRecord]:

        rows = self.connection.execute(
            """
            SELECT *
            FROM organisation_proposals
            WHERE decision_run_id = ?
            ORDER BY id
            """,
            (decision_run_id,),
        ).fetchall()

        return [
            self._proposal_from_row(row)
            for row in rows
        ]

    def list_by_media(
        self,
        media_id: int,
    ) -> list[OrganisationProposalRecord]:

        rows = self.connection.execute(
            """
            SELECT *
            FROM organisation_proposals
            WHERE media_id = ?
            ORDER BY id DESC
            """,
            (media_id,),
        ).fetchall()

        return [
            self._proposal_from_row(row)
            for row in rows
        ]

    def list_by_states(
        self,
        states: tuple,
    ) -> list[OrganisationProposalRecord]:

        if not states:
            return []

        placeholders = ",".join("?" for _ in states)

        rows = self.connection.execute(
            f"""
            SELECT *
            FROM organisation_proposals
            WHERE state IN ({placeholders})
            ORDER BY id
            """,
            tuple(states),
        ).fetchall()

        return [
            self._proposal_from_row(row)
            for row in rows
        ]

    def events_for(
        self,
        proposal_id: int,
    ) -> list[dict]:

        rows = self.connection.execute(
            """
            SELECT
                event_type,
                previous_state,
                new_state,
                actor,
                detail,
                created_at
            FROM organisation_proposal_events
            WHERE proposal_id = ?
            ORDER BY id
            """,
            (proposal_id,),
        ).fetchall()

        return [
            {
                "event_type": row[0],
                "previous_state": row[1],
                "new_state": row[2],
                "actor": row[3],
                "detail": row[4],
                "created_at": row[5],
            }
            for row in rows
        ]

    # ---------------------------------------------------------
    # lifecycle transitions
    # ---------------------------------------------------------

    def transition(
        self,
        proposal_id: int,
        *,
        new_state: str,
        expected_current: tuple,
        actor: str = "system",
        detail: str | None = None,
    ) -> OrganisationProposalRecord:
        """
        Move one proposal to `new_state`, validating against the
        persisted current state and appending the corresponding
        immutable event.

        Commits on success: human decisions are durable.
        """

        current = self.get_proposal(proposal_id)

        if current is None:
            raise OrganisationError(
                f"organisation proposal {proposal_id} "
                f"not found"
            )

        if current.state not in expected_current:
            raise OrganisationError(
                f"organisation proposal {proposal_id} is "
                f"'{current.state}'; expected one of "
                f"{sorted(expected_current)}"
            )

        assert_transition(current.state, new_state)

        cursor = self.connection.cursor()

        cursor.execute(
            """
            UPDATE organisation_proposals
            SET
                state = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                new_state,
                proposal_id,
            ),
        )

        self._record_event(
            cursor,
            proposal_id=proposal_id,
            event_type=new_state,
            previous_state=current.state,
            new_state=new_state,
            actor=actor,
            detail=detail,
        )

        self.connection.commit()

        return self.get_proposal(proposal_id)

    def supersede_proposals(
        self,
        proposal_ids: list[int],
        *,
        new_decision_run_id: int,
    ) -> int:
        """
        Supersede currently-proposed proposals from OLDER
        decision runs because a newer decision run has produced
        fresh outputs for their lineages.

        Only 'proposed' rows are superseded: accepted and
        rejected proposals are durable human decisions and are
        never rewritten by intelligence. Appends an immutable
        'superseded' event citing the newer decision run.

        No commit: called inside the generation transaction.
        """

        superseded = 0

        for proposal_id in proposal_ids:

            current = self.get_proposal(proposal_id)

            if current is None:
                continue

            if current.state != "proposed":
                continue

            if (
                current.decision_run_id
                >= new_decision_run_id
            ):
                continue

            cursor = self.connection.cursor()

            cursor.execute(
                """
                UPDATE organisation_proposals
                SET
                    state = 'superseded',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                  AND state = 'proposed'
                """,
                (proposal_id,),
            )

            detail = json.dumps(
                {
                    "reason": "newer_decision_run",
                    "new_decision_run_id": (
                        new_decision_run_id
                    ),
                }
            )

            self._record_event(
                cursor,
                proposal_id=proposal_id,
                event_type="superseded",
                previous_state="proposed",
                new_state="superseded",
                actor="organisation_intelligence",
                detail=detail,
            )

            superseded += 1

        return superseded

    # ---------------------------------------------------------
    # internals
    # ---------------------------------------------------------

    @staticmethod
    def _record_event(
        cursor,
        *,
        proposal_id: int,
        event_type: str,
        previous_state: str | None,
        new_state: str | None,
        actor: str,
        detail: str | None,
    ) -> None:

        cursor.execute(
            """
            INSERT INTO organisation_proposal_events (
                proposal_id,
                event_type,
                previous_state,
                new_state,
                actor,
                detail
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                proposal_id,
                event_type,
                previous_state,
                new_state,
                actor,
                detail,
            ),
        )

    def _proposal_from_row(
        self,
        row,
    ) -> OrganisationProposalRecord:

        # Positional access mirrors the migration 025 DDL and
        # keeps this repository independent of the caller's
        # row_factory.

        def _load(value, fallback):
            if value is None:
                return fallback
            try:
                loaded = json.loads(value)
            except (TypeError, ValueError):
                return fallback
            return loaded

        return OrganisationProposalRecord(
            id=row[0],
            decision_run_id=row[1],
            media_id=row[2],
            related_media_id=row[3],
            intent=row[4],
            proposed_destination=row[5],
            proposed_name=row[6],
            confidence=row[7],
            risk=row[8],
            rationale=_load(row[9], []),
            evidence=_load(row[10], {}),
            intelligence_identity=row[11],
            state=row[12],
            created_at=row[13],
            updated_at=row[14],
        )

    def _decision_run_from_row(
        self,
        row,
    ) -> OrganisationDecisionRunRecord:

        def _load(value, fallback):
            if value is None:
                return fallback
            try:
                loaded = json.loads(value)
            except (TypeError, ValueError):
                return fallback
            return loaded

        def _column(index, fallback=None):
            # Sprint 15 columns are appended at the end;
            # older databases simply lack them.
            try:
                return row[index]
            except IndexError:
                return fallback

        return OrganisationDecisionRunRecord(
            id=row[0],
            status=row[1],
            library_roots=_load(row[2], []),
            rule_versions=_load(row[3], {}),
            policy_values=_load(row[4], {}),
            git_revision=row[5],
            identity_digest=row[6],
            lineages_considered=row[7],
            proposals_created=row[8],
            hash_coverage_total=row[9],
            hash_coverage_hashed=row[10],
            error_message=row[11],
            created_at=row[12],
            profile_id=_column(13),
            profile_digest=_column(14),
            metadata_fingerprint=_column(15),
            mutation_strategy=_column(16),
            operation_count=_column(17),
            strategy_reasoning=_load(_column(18), []),
        )

    # ---------------------------------------------------------
    # Sprint 15: profiles
    # ---------------------------------------------------------

    def create_profile(
        self,
        *,
        name: str,
        payload: dict,
        digest: str,
    ) -> int:
        """
        Store one new organisation profile. Names are
        unique: a duplicate raises OrganisationError so
        the service can report it plainly. No commit:
        callers own the transaction.
        """

        cursor = self.connection.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO organisation_profiles (
                    name,
                    payload_json,
                    digest,
                    updated_at
                )
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    name,
                    json.dumps(dict(payload or {})),
                    digest or "",
                ),
            )
        except Exception as error:

            # A failed INSERT leaves SQLite's implicit transaction
            # open. Release it before reporting the refusal so the
            # next write does not fail with "database is locked".
            self.connection.rollback()

            if "UNIQUE" in str(error).upper():
                raise OrganisationError(
                    "Profile name already exists. Choose "
                    "a different name."
                ) from error

            raise

        return cursor.lastrowid

    def update_profile(
        self,
        profile_id: int,
        *,
        name: str,
        payload: dict,
        digest: str,
    ) -> None:
        """
        Update one stored profile in place (rename
        allowed). A rename colliding with another
        profile raises OrganisationError. Unknown ids
        raise OrganisationError. No commit: callers
        own the transaction.
        """

        cursor = self.connection.cursor()

        cursor.execute(
            """
            SELECT id FROM organisation_profiles
            WHERE id = ?
            """,
            (profile_id,),
        )

        if cursor.fetchone() is None:
            raise OrganisationError(
                f"organisation profile {profile_id} not found"
            )

        try:
            cursor.execute(
                """
                UPDATE organisation_profiles
                SET name = ?,
                    payload_json = ?,
                    digest = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    name,
                    json.dumps(dict(payload or {})),
                    digest or "",
                    profile_id,
                ),
            )
        except Exception as error:

            # A failed UPDATE leaves SQLite's implicit transaction
            # open. Release it before reporting the refusal so the
            # next write does not fail with "database is locked".
            self.connection.rollback()

            if "UNIQUE" in str(error).upper():
                raise OrganisationError(
                    "Profile name already exists. Choose "
                    "a different name."
                ) from error

            raise

    def delete_profile(self, profile_id: int) -> str | None:
        """
        Delete exactly one stored profile by id and
        return its name (None when absent). Never
        matches by name: two profiles can never share
        a name, and preset origin never links rows.
        No commit: callers own the transaction.
        """

        cursor = self.connection.cursor()

        cursor.execute(
            """
            SELECT name FROM organisation_profiles
            WHERE id = ?
            """,
            (profile_id,),
        )

        row = cursor.fetchone()

        if row is None:
            return None

        cursor.execute(
            """
            DELETE FROM organisation_profiles
            WHERE id = ?
            """,
            (profile_id,),
        )

        return row[0]

    def get_profile(
        self,
        profile_id: int,
    ) -> OrganisationProfileRecord | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM organisation_profiles
            WHERE id = ?
            """,
            (profile_id,),
        ).fetchone()

        if row is None:
            return None

        return self._profile_from_row(row)

    def get_profile_by_name(
        self,
        name: str,
    ) -> OrganisationProfileRecord | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM organisation_profiles
            WHERE name = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (name,),
        ).fetchone()

        if row is None:
            return None

        return self._profile_from_row(row)

    def list_profiles(self) -> list:
        rows = self.connection.execute(
            """
            SELECT *
            FROM organisation_profiles
            ORDER BY id DESC
            """
        ).fetchall()

        return [self._profile_from_row(row) for row in rows]

    def _profile_from_row(
        self,
        row,
    ) -> OrganisationProfileRecord:
        # Column layout depends on migration 040 (which
        # drops the version column): tolerate both so a
        # database that has not migrated yet still reads.
        if len(row) > 6:
            payload_raw, digest_raw = row[3], row[4]
            created_raw = row[5]
            updated_raw = row[6]
        else:
            payload_raw, digest_raw = row[2], row[3]
            created_raw = row[4] if len(row) > 4 else None
            updated_raw = row[5] if len(row) > 5 else None

        try:
            payload = json.loads(payload_raw or "{}")
        except (TypeError, ValueError):
            payload = {}

        if not isinstance(payload, dict):
            payload = {}

        return OrganisationProfileRecord(
            id=row[0],
            name=row[1] or "",
            payload=payload,
            digest=digest_raw or "",
            created_at=created_raw,
            updated_at=updated_raw,
        )

    # ---------------------------------------------------------
    # Sprint 15: integration settings (non-secret only)
    # ---------------------------------------------------------

    def save_integration(
        self,
        *,
        provider: str,
        enabled: bool,
        base_url: str,
        jellyfin_user_id: str | None = None,
        secret_ref: str = "",
    ) -> int:
        """
        Upsert non-secret integration configuration. No
        commit: callers own the transaction. Credential
        values must never reach this method.
        """

        if provider not in (
            "jellyfin", "radarr", "sonarr"
        ):
            raise OrganisationError(
                f"unknown provider '{provider}'"
            )

        cursor = self.connection.cursor()

        cursor.execute(
            """
            INSERT INTO integration_settings (
                provider,
                enabled,
                base_url,
                jellyfin_user_id,
                secret_ref,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(provider) DO UPDATE SET
                enabled = excluded.enabled,
                base_url = excluded.base_url,
                jellyfin_user_id = (
                    excluded.jellyfin_user_id
                ),
                secret_ref = excluded.secret_ref,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                provider,
                1 if enabled else 0,
                base_url or "",
                jellyfin_user_id,
                secret_ref or "",
            ),
        )

        row = cursor.execute(
            """
            SELECT id FROM integration_settings
            WHERE provider = ?
            """,
            (provider,),
        ).fetchone()

        return row[0]

    def get_integration(
        self,
        provider: str,
    ) -> IntegrationSettingsRecord | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM integration_settings
            WHERE provider = ?
            """,
            (provider,),
        ).fetchone()

        if row is None:
            return None

        return self._integration_from_row(row)

    def list_integrations(self) -> list:
        rows = self.connection.execute(
            """
            SELECT *
            FROM integration_settings
            ORDER BY provider
            """
        ).fetchall()

        return [self._integration_from_row(row) for row in rows]

    def _integration_from_row(
        self,
        row,
    ) -> IntegrationSettingsRecord:
        return IntegrationSettingsRecord(
            id=row[0],
            provider=row[1] or "",
            enabled=bool(row[2]),
            base_url=row[3] or "",
            jellyfin_user_id=row[4],
            secret_ref=row[5] or "",
            created_at=row[6] if len(row) > 6 else None,
            updated_at=row[7] if len(row) > 7 else None,
        )

    # ---------------------------------------------------------
    # Sprint 15 final correction: explicit provider-root to
    # local-root mappings (deterministic association across
    # container/host filesystem namespaces).
    # ---------------------------------------------------------

    def list_path_mappings(
        self, provider: str | None = None
    ) -> list:
        """List explicit root mappings, optionally filtered."""

        if provider is not None:
            rows = self.connection.execute(
                """
                SELECT id, provider, provider_root,
                       local_root, created_at
                FROM provider_path_mappings
                WHERE provider = ?
                ORDER BY provider, provider_root
                """,
                (provider,),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT id, provider, provider_root,
                       local_root, created_at
                FROM provider_path_mappings
                ORDER BY provider, provider_root
                """
            ).fetchall()

        return [
            {
                "id": row[0],
                "provider": row[1] or "",
                "provider_root": row[2] or "",
                "local_root": row[3] or "",
                "created_at": row[4],
            }
            for row in rows
        ]

    def save_path_mapping(
        self,
        *,
        provider: str,
        provider_root: str,
        local_root: str,
    ) -> dict:
        """
        Insert or replace one explicit root mapping. Both
        roots are stored normalised (forward slashes, no
        trailing slash except the filesystem root). No
        commit: callers own the transaction.
        """

        if provider not in (
            "jellyfin", "radarr", "sonarr"
        ):
            raise OrganisationError(
                f"unknown provider '{provider}'"
            )

        clean_provider_root = self._normalise_mapping_root(
            provider_root, "provider root"
        )
        clean_local_root = self._normalise_mapping_root(
            local_root, "local root"
        )

        cursor = self.connection.cursor()

        cursor.execute(
            """
            INSERT INTO provider_path_mappings (
                provider, provider_root, local_root
            )
            VALUES (?, ?, ?)
            ON CONFLICT(
                provider, provider_root, local_root
            ) DO NOTHING
            """,
            (
                provider,
                clean_provider_root,
                clean_local_root,
            ),
        )

        row = cursor.execute(
            """
            SELECT id, provider, provider_root,
                   local_root, created_at
            FROM provider_path_mappings
            WHERE provider = ? AND provider_root = ?
              AND local_root = ?
            """,
            (
                provider,
                clean_provider_root,
                clean_local_root,
            ),
        ).fetchone()

        return {
            "id": row[0],
            "provider": row[1] or "",
            "provider_root": row[2] or "",
            "local_root": row[3] or "",
            "created_at": row[4],
        }

    def delete_path_mapping(self, mapping_id: int) -> bool:
        """Delete one explicit root mapping. No commit."""

        cursor = self.connection.cursor()

        cursor.execute(
            """
            DELETE FROM provider_path_mappings
            WHERE id = ?
            """,
            (int(mapping_id),),
        )

        return cursor.rowcount > 0

    @staticmethod
    def _normalise_mapping_root(value, label: str) -> str:
        text = str(value or "").strip().replace("\\", "/")

        if not text.startswith("/"):
            raise OrganisationError(
                f"{label} must be an absolute path "
                f"(got {value!r})"
            )

        cleaned = text.rstrip("/")

        if not cleaned:
            if label == "provider root":
                raise OrganisationError(
                    "provider root must not be the bare "
                    "filesystem root; map a real library "
                    "root such as /Movies"
                )

            return "/"

        return cleaned

    # ---------------------------------------------------------
    # Sprint 15: metadata observations
    # ---------------------------------------------------------

    def record_metadata_observation(
        self,
        *,
        media_id: int,
        provider: str,
        provider_item_id: str,
        provider_item_kind: str,
        source_fingerprint: str,
        association_strength: str,
        association_basis: str = "",
        payload: dict | None = None,
    ) -> int:
        """
        Append one immutable provider metadata snapshot.
        Rows are never updated; re-fetches with a new
        fingerprint append new rows. No commit: callers
        own the transaction. Payloads must never contain
        credential values.
        """

        cursor = self.connection.cursor()

        cursor.execute(
            """
            INSERT INTO metadata_observations (
                media_id,
                provider,
                provider_item_id,
                provider_item_kind,
                source_fingerprint,
                association_strength,
                association_basis,
                payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(
                media_id, provider, provider_item_id,
                source_fingerprint
            ) DO NOTHING
            """,
            (
                media_id,
                provider,
                str(provider_item_id),
                provider_item_kind,
                source_fingerprint,
                association_strength,
                association_basis or "",
                json.dumps(dict(payload or {})),
            ),
        )

        row = cursor.execute(
            """
            SELECT id FROM metadata_observations
            WHERE media_id = ?
              AND provider = ?
              AND provider_item_id = ?
              AND source_fingerprint = ?
            """,
            (
                media_id,
                provider,
                str(provider_item_id),
                source_fingerprint,
            ),
        ).fetchone()

        return row[0]

    def list_metadata_observations(
        self,
        media_id: int,
    ) -> list:
        rows = self.connection.execute(
            """
            SELECT *
            FROM metadata_observations
            WHERE media_id = ?
            ORDER BY id
            """,
            (media_id,),
        ).fetchall()

        return [
            self._metadata_observation_from_row(row)
            for row in rows
        ]

    def latest_metadata_observation(
        self,
        media_id: int,
        provider: str,
        provider_item_id: str,
    ) -> MetadataObservationRecord | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM metadata_observations
            WHERE media_id = ?
              AND provider = ?
              AND provider_item_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (media_id, provider, str(provider_item_id)),
        ).fetchone()

        if row is None:
            return None

        return self._metadata_observation_from_row(row)

    def _metadata_observation_from_row(
        self,
        row,
    ) -> MetadataObservationRecord:
        try:
            payload = json.loads(row[9] or "{}")
        except (TypeError, ValueError):
            payload = {}

        if not isinstance(payload, dict):
            payload = {}

        return MetadataObservationRecord(
            id=row[0],
            media_id=row[1],
            provider=row[2] or "",
            provider_item_id=str(row[3] or ""),
            provider_item_kind=row[4] or "",
            retrieved_at=row[5],
            source_fingerprint=row[6] or "",
            association_strength=row[7] or "",
            association_basis=row[8] or "",
            payload=payload,
            created_at=row[10] if len(row) > 10 else None,
        )

    @staticmethod
    def metadata_fingerprint(payload: dict) -> str:
        """
        Deterministic sha256 over the normalised relevant
        metadata payload. Equal relevant inputs always
        produce equal fingerprints.
        """

        import hashlib

        canonical = json.dumps(
            payload or {},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

        return hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest()

    def recent_metadata_observations(
        self,
        limit: int = 500,
    ) -> list:
        """
        Newest metadata observation rows first, bounded.
        Read-only helper for preflight provider-path
        collection and status surfaces.
        """

        rows = self.connection.execute(
            """
            SELECT *
            FROM metadata_observations
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()

        return [
            self._metadata_observation_from_row(row)
            for row in rows
        ]

    def observations_with_lineage_paths(
        self,
        provider: str | None = None,
    ) -> list:
        """
        Every metadata observation joined to its
        lineage file path (None when the lineage row is
        gone). Read-only; powers the kind-compatibility
        assessment and append-only withdrawal of
        observations attached to the wrong lineage kind.
        Returns dicts with observation, lineage path,
        and lineage media type.
        """

        if provider is not None:
            rows = self.connection.execute(
                """
                SELECT o.*, m.file_path, m.media_type
                FROM metadata_observations o
                LEFT JOIN media_items m
                  ON m.id = o.media_id
                WHERE o.provider = ?
                ORDER BY o.id
                """,
                (provider,),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT o.*, m.file_path, m.media_type
                FROM metadata_observations o
                LEFT JOIN media_items m
                  ON m.id = o.media_id
                ORDER BY o.id
                """
            ).fetchall()

        joined = []

        for row in rows:
            observation = (
                self._metadata_observation_from_row(row)
            )

            joined.append(
                {
                    "observation": observation,
                    "file_path": row[11]
                    if len(row) > 11
                    else None,
                    "media_type": row[12]
                    if len(row) > 12
                    else None,
                }
            )

        return joined

    # ---------------------------------------------------------
    # Sprint 15 productisation: metadata sync run ledger
    # ---------------------------------------------------------

    def record_metadata_sync_start(
        self,
        provider: str,
    ) -> int:
        """
        Open one sync run row in state running. No commit:
        callers own the transaction.
        """

        cursor = self.connection.cursor()

        cursor.execute(
            """
            INSERT INTO metadata_sync_runs (provider)
            VALUES (?)
            """,
            (provider,),
        )

        return cursor.lastrowid

    def finish_metadata_sync_run(
        self,
        run_id: int,
        *,
        state: str,
        total_items: int = 0,
        inspected: int = 0,
        matched: int = 0,
        updated: int = 0,
        unchanged: int = 0,
        unmatched: int = 0,
        needs_review: int = 0,
        error_count: int = 0,
        error_text: str = "",
    ) -> None:
        """
        Close one sync run row with its honest counters.
        No commit: callers own the transaction.
        """

        if state not in ("succeeded", "failed"):
            raise ValueError(
                f"sync run state must be succeeded or "
                f"failed, got {state!r}"
            )

        self.connection.execute(
            """
            UPDATE metadata_sync_runs
            SET finished_at = CURRENT_TIMESTAMP,
                state = ?,
                total_items = ?,
                inspected = ?,
                matched = ?,
                updated = ?,
                unchanged = ?,
                unmatched = ?,
                needs_review = ?,
                error_count = ?,
                error_text = ?
            WHERE id = ?
            """,
            (
                state,
                int(total_items),
                int(inspected),
                int(matched),
                int(updated),
                int(unchanged),
                int(unmatched),
                int(needs_review),
                int(error_count),
                str(error_text or ""),
                int(run_id),
            ),
        )

    def latest_sync_run(
        self,
        provider: str,
    ) -> dict | None:
        """Newest sync run row for one provider, or None."""

        row = self.connection.execute(
            """
            SELECT id, provider, started_at, finished_at,
                   state, total_items, inspected,
                   matched, updated, unchanged, unmatched,
                   needs_review, error_count, error_text
            FROM metadata_sync_runs
            WHERE provider = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (provider,),
        ).fetchone()

        if row is None:
            return None

        return {
            "id": row[0],
            "provider": row[1] or "",
            "started_at": row[2],
            "finished_at": row[3],
            "state": row[4] or "",
            "total_items": row[5] or 0,
            "inspected": row[6] or 0,
            "matched": row[7] or 0,
            "updated": row[8] or 0,
            "unchanged": row[9] or 0,
            "unmatched": row[10] or 0,
            "needs_review": row[11] or 0,
            "error_count": row[12] or 0,
            "error_text": row[13] or "",
        }

    # ---------------------------------------------------------
    # Sprint 15: scope actions
    # ---------------------------------------------------------

    def create_scope_action(
        self,
        *,
        decision_run_id: int,
        scope_path: str,
        action_type: str,
        source_path: str,
        destination_path: str,
        descendant_manifest: list,
        strategy: str,
        operation_count: int,
        reasoning: list,
        review_conditions: list,
        descendant_proposal_ids: list,
        intelligence_identity: str | None,
    ) -> int:
        """
        Persist one scope-level action AS PRODUCED BY ITS
        DECISION RUN in state 'proposed'. No commit: the
        caller commits the whole decision run atomically.
        """

        from app.models.organisation import (
            SCOPE_ACTION_TYPES,
        )

        if action_type not in SCOPE_ACTION_TYPES:
            raise OrganisationError(
                f"unknown scope action type '{action_type}'"
            )

        cursor = self.connection.cursor()

        cursor.execute(
            """
            INSERT INTO organisation_scope_actions (
                decision_run_id,
                scope_path,
                action_type,
                source_path,
                destination_path,
                descendant_manifest_json,
                strategy,
                operation_count,
                reasoning_json,
                review_conditions_json,
                descendant_proposal_ids_json,
                intelligence_identity,
                state
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    'proposed')
            """,
            (
                decision_run_id,
                scope_path,
                action_type,
                source_path,
                destination_path,
                json.dumps(list(descendant_manifest or [])),
                strategy or "",
                int(operation_count or 0),
                json.dumps(list(reasoning or [])),
                json.dumps(
                    list(review_conditions or [])
                ),
                json.dumps(
                    list(descendant_proposal_ids or [])
                ),
                intelligence_identity,
            ),
        )

        action_id = cursor.lastrowid

        self._record_scope_event(
            cursor,
            scope_action_id=action_id,
            event_type="proposed",
            previous_state=None,
            new_state="proposed",
            actor="organisation_intelligence",
            detail=None,
        )

        return action_id

    def get_scope_action(
        self,
        action_id: int,
    ) -> OrganisationScopeActionRecord | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM organisation_scope_actions
            WHERE id = ?
            """,
            (action_id,),
        ).fetchone()

        if row is None:
            return None

        return self._scope_action_from_row(row)

    def list_scope_actions_by_run(
        self,
        decision_run_id: int,
    ) -> list:
        rows = self.connection.execute(
            """
            SELECT *
            FROM organisation_scope_actions
            WHERE decision_run_id = ?
            ORDER BY id
            """,
            (decision_run_id,),
        ).fetchall()

        return [self._scope_action_from_row(r) for r in rows]

    def list_scope_actions_by_states(
        self,
        states: tuple,
    ) -> list:
        if not states:
            return []

        placeholders = ",".join("?" for _ in states)

        rows = self.connection.execute(
            f"""
            SELECT *
            FROM organisation_scope_actions
            WHERE state IN ({placeholders})
            ORDER BY id
            """,
            tuple(states),
        ).fetchall()

        return [self._scope_action_from_row(r) for r in rows]

    def scope_events_for(self, action_id: int) -> list:
        rows = self.connection.execute(
            """
            SELECT *
            FROM organisation_scope_action_events
            WHERE scope_action_id = ?
            ORDER BY id
            """,
            (action_id,),
        ).fetchall()

        return [dict(row) for row in rows]

    def transition_scope_action(
        self,
        action_id: int,
        *,
        new_state: str,
        expected_current: tuple,
        actor: str = "system",
        detail: str | None = None,
    ) -> OrganisationScopeActionRecord:
        """
        Move one scope action to `new_state` with an
        immutable event. Commits on success.
        """

        current = self.get_scope_action(action_id)

        if current is None:
            raise OrganisationError(
                f"organisation scope action {action_id} "
                f"not found"
            )

        if current.state not in expected_current:
            raise OrganisationError(
                f"organisation scope action {action_id} "
                f"is '{current.state}'; expected one of "
                f"{sorted(expected_current)}"
            )

        assert_transition(current.state, new_state)

        cursor = self.connection.cursor()

        cursor.execute(
            """
            UPDATE organisation_scope_actions
            SET
                state = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (new_state, action_id),
        )

        self._record_scope_event(
            cursor,
            scope_action_id=action_id,
            event_type=new_state,
            previous_state=current.state,
            new_state=new_state,
            actor=actor,
            detail=detail,
        )

        self.connection.commit()

        return self.get_scope_action(action_id)

    def accept_scope_action(
        self,
        action_id: int,
        *,
        actor: str = "human",
    ) -> OrganisationScopeActionRecord:
        """
        Approve one scope action AND atomically transition
        its covered descendant per-file proposals from
        'proposed' to 'accepted', preserving per-item
        events. A descendant that is no longer 'proposed'
        aborts the whole acceptance: scope approval can
        never silently skip or invent per-file decisions.
        Commits on success.
        """

        action = self.get_scope_action(action_id)

        if action is None:
            raise OrganisationError(
                f"organisation scope action {action_id} "
                f"not found"
            )

        if action.state != "proposed":
            raise OrganisationError(
                f"organisation scope action {action_id} "
                f"is '{action.state}'; only proposed "
                f"scope actions may be accepted"
            )

        covered = list(action.descendant_proposal_ids or [])

        for proposal_id in covered:
            proposal = self.get_proposal(proposal_id)

            if proposal is None:
                raise OrganisationError(
                    f"scope action {action_id} covers "
                    f"unknown proposal {proposal_id}; "
                    f"refusing scope approval"
                )

            if proposal.state != "proposed":
                raise OrganisationError(
                    f"scope action {action_id} covers "
                    f"proposal {proposal_id} in state "
                    f"'{proposal.state}'; refusing scope "
                    f"approval"
                )

        cursor = self.connection.cursor()

        cursor.execute(
            """
            UPDATE organisation_scope_actions
            SET
                state = 'accepted',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (action_id,),
        )

        self._record_scope_event(
            cursor,
            scope_action_id=action_id,
            event_type="accepted",
            previous_state="proposed",
            new_state="accepted",
            actor=actor,
            detail=(
                f"scope approval covering "
                f"{len(covered)} descendant proposals"
            ),
        )

        for proposal_id in covered:
            cursor.execute(
                """
                UPDATE organisation_proposals
                SET
                    state = 'accepted',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (proposal_id,),
            )

            self._record_event(
                cursor,
                proposal_id=proposal_id,
                event_type="accepted",
                previous_state="proposed",
                new_state="accepted",
                actor=actor,
                detail=(
                    f"accepted via scope action {action_id}"
                ),
            )

        self.connection.commit()

        return self.get_scope_action(action_id)

    def supersede_scope_actions(
        self,
        action_ids: list[int],
        *,
        new_decision_run_id: int,
    ) -> int:
        """
        Supersede currently-proposed scope actions from
        older runs. No commit: called inside the
        generation transaction.
        """

        superseded = 0

        for action_id in action_ids:
            current = self.get_scope_action(action_id)

            if current is None:
                continue

            if current.state != "proposed":
                continue

            if current.decision_run_id >= new_decision_run_id:
                continue

            cursor = self.connection.cursor()

            cursor.execute(
                """
                UPDATE organisation_scope_actions
                SET
                    state = 'superseded',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                  AND state = 'proposed'
                """,
                (action_id,),
            )

            self._record_scope_event(
                cursor,
                scope_action_id=action_id,
                event_type="superseded",
                previous_state="proposed",
                new_state="superseded",
                actor="organisation_intelligence",
                detail=json.dumps(
                    {
                        "reason": "newer_decision_run",
                        "new_decision_run_id": (
                            new_decision_run_id
                        ),
                    }
                ),
            )

            superseded += 1

        return superseded

    def _scope_action_from_row(
        self,
        row,
    ) -> OrganisationScopeActionRecord:
        def _load(value, fallback):
            if value is None:
                return fallback
            try:
                loaded = json.loads(value)
            except (TypeError, ValueError):
                return fallback
            return loaded if isinstance(
                loaded, type(fallback)
            ) else fallback

        return OrganisationScopeActionRecord(
            id=row[0],
            decision_run_id=row[1],
            scope_path=row[2] or "",
            action_type=row[3] or "",
            source_path=row[4] or "",
            destination_path=row[5] or "",
            descendant_manifest=_load(row[6], []),
            strategy=row[7] or "",
            operation_count=row[8] or 0,
            reasoning=_load(row[9], []),
            review_conditions=_load(row[10], []),
            descendant_proposal_ids=_load(row[11], []),
            intelligence_identity=row[12],
            state=row[13],
            created_at=row[14] if len(row) > 14 else None,
            updated_at=row[15] if len(row) > 15 else None,
        )

    @staticmethod
    def _record_scope_event(
        cursor,
        *,
        scope_action_id: int,
        event_type: str,
        previous_state: str | None,
        new_state: str,
        actor: str,
        detail: str | None,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO organisation_scope_action_events (
                scope_action_id,
                event_type,
                previous_state,
                new_state,
                actor,
                detail
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                scope_action_id,
                event_type,
                previous_state,
                new_state,
                actor,
                detail,
            ),
        )

    # ---------------------------------------------------------
    # Sprint 15: scope executions
    # ---------------------------------------------------------

    def create_scope_execution(
        self,
        *,
        scope_action_id: int,
        decision_run_id: int,
        action_type: str,
        source_path: str,
        destination_path: str,
        descendant_manifest: list,
        actor: str = "human",
    ) -> int:
        """
        Open one scope execution in state 'proposed'.
        scope_action_id is UNIQUE: one execution per
        approved scope action. No commit: callers own
        the transaction.
        """

        cursor = self.connection.cursor()

        cursor.execute(
            """
            INSERT INTO organisation_scope_executions (
                scope_action_id,
                decision_run_id,
                action_type,
                source_path,
                destination_path,
                descendant_manifest_json,
                state,
                actor
            )
            VALUES (?, ?, ?, ?, ?, ?, 'proposed', ?)
            """,
            (
                scope_action_id,
                decision_run_id,
                action_type,
                source_path,
                destination_path,
                json.dumps(
                    list(descendant_manifest or [])
                ),
                actor,
            ),
        )

        execution_id = cursor.lastrowid

        self._record_scope_execution_event(
            cursor,
            scope_execution_id=execution_id,
            event_type="proposed",
            previous_state=None,
            new_state="proposed",
            actor=actor,
            detail=None,
        )

        return execution_id

    def get_scope_execution(
        self,
        execution_id: int,
    ) -> OrganisationScopeExecutionRecord | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM organisation_scope_executions
            WHERE id = ?
            """,
            (execution_id,),
        ).fetchone()

        if row is None:
            return None

        return self._scope_execution_from_row(row)

    def get_scope_execution_by_action(
        self,
        scope_action_id: int,
    ) -> OrganisationScopeExecutionRecord | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM organisation_scope_executions
            WHERE scope_action_id = ?
            """,
            (scope_action_id,),
        ).fetchone()

        if row is None:
            return None

        return self._scope_execution_from_row(row)

    def list_scope_executions(self, limit: int = 100) -> list:
        rows = self.connection.execute(
            """
            SELECT *
            FROM organisation_scope_executions
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        return [self._scope_execution_from_row(r) for r in rows]

    def update_scope_execution_state(
        self,
        execution_id: int,
        *,
        state: str,
        error: str | None = None,
        descendants_completed: list | None = None,
        clear_error: bool = False,
    ) -> OrganisationScopeExecutionRecord:
        """
        Advance one scope execution through the shared
        lifecycle vocabulary. Commits on success with an
        immutable event.
        """

        from app.models.organisation_execution import (
            assert_transition,
        )

        current = self.get_scope_execution(execution_id)

        if current is None:
            raise OrganisationError(
                f"organisation scope execution "
                f"{execution_id} not found"
            )

        _assert_scope_execution_transition(
            current.state, state
        )

        cursor = self.connection.cursor()

        assignments = ["state = ?"]
        values = [state]

        if error is not None or clear_error:
            assignments.append("error = ?")
            values.append(None if clear_error else error)

        if descendants_completed is not None:
            assignments.append("descendants_completed_json = ?")
            values.append(
                json.dumps(list(descendants_completed))
            )

        assignments.append("updated_at = CURRENT_TIMESTAMP")

        cursor.execute(
            f"""
            UPDATE organisation_scope_executions
            SET {", ".join(assignments)}
            WHERE id = ?
            """,
            (*values, execution_id),
        )

        self._record_scope_execution_event(
            cursor,
            scope_execution_id=execution_id,
            event_type=state,
            previous_state=current.state,
            new_state=state,
            actor="system",
            detail=error,
        )

        self.connection.commit()

        return self.get_scope_execution(execution_id)

    def scope_execution_events_for(
        self,
        execution_id: int,
    ) -> list:
        rows = self.connection.execute(
            """
            SELECT *
            FROM organisation_scope_execution_events
            WHERE scope_execution_id = ?
            ORDER BY id
            """,
            (execution_id,),
        ).fetchall()

        return [dict(row) for row in rows]

    def _scope_execution_from_row(
        self,
        row,
    ) -> OrganisationScopeExecutionRecord:
        try:
            manifest = json.loads(row[6] or "[]")
        except (TypeError, ValueError):
            manifest = []

        if not isinstance(manifest, list):
            manifest = []

        try:
            completed = json.loads(row[9] or "[]")
        except (TypeError, ValueError):
            completed = []

        if not isinstance(completed, list):
            completed = []

        return OrganisationScopeExecutionRecord(
            id=row[0],
            scope_action_id=row[1],
            decision_run_id=row[2],
            action_type=row[3] or "",
            source_path=row[4] or "",
            destination_path=row[5] or "",
            descendant_manifest=manifest,
            state=row[7],
            error=row[8],
            descendants_completed=completed,
            actor=row[10] or "human",
            created_at=row[11] if len(row) > 11 else None,
            updated_at=row[12] if len(row) > 12 else None,
        )

    @staticmethod
    def _record_scope_execution_event(
        cursor,
        *,
        scope_execution_id: int,
        event_type: str,
        previous_state: str | None,
        new_state: str,
        actor: str,
        detail: str | None,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO organisation_scope_execution_events (
                scope_execution_id,
                event_type,
                previous_state,
                new_state,
                actor,
                detail
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                scope_execution_id,
                event_type,
                previous_state,
                new_state,
                actor,
                detail,
            ),
        )


    # Sprint 15: scope claims and scope continuity
    # ---------------------------------------------------------

    def claim_scope_paths(
        self,
        scope_execution_id: int,
        paths: list,
    ) -> None:
        """
        Atomically claim scope paths (source/destination
        directory pairs) for one scope execution. Path
        UNIQUE serialises conflicting structural operations
        exactly like per-file scope claims. Caller owns the
        surrounding state transition transaction.
        """

        import sqlite3

        cursor = self.connection.cursor()

        try:
            cursor.execute(
                """
                DELETE FROM organisation_scope_claims
                WHERE scope_execution_id = ?
                """,
                (scope_execution_id,),
            )

            for path, role in paths:
                cursor.execute(
                    """
                    INSERT INTO organisation_scope_claims (
                        scope_execution_id, path, role
                    ) VALUES (?, ?, ?)
                    """,
                    (scope_execution_id, path, role),
                )
        except sqlite3.IntegrityError as error:
            self.connection.rollback()

            raise OrganisationError(
                f"scope claim conflict for organisation "
                f"scope execution {scope_execution_id}: "
                f"{error}"
            ) from error

    def release_scope_paths(self, scope_execution_id) -> None:
        self.connection.execute(
            """
            DELETE FROM organisation_scope_claims
            WHERE scope_execution_id = ?
            """,
            (scope_execution_id,),
        )

        self.connection.commit()

    def claim_scope_execution(
        self,
        scope_execution_id: int,
    ):
        """
        Atomically transition a scope execution from
        'precondition_verified' to 'executing' while
        claiming its source and destination paths. Mirrors
        per-file claim_scope: UNIQUE(path) serialises
        conflicting structural operations regardless of
        process interleaving. The filesystem mutation may
        only proceed after this call commits.
        """

        import sqlite3

        current = self.get_scope_execution(scope_execution_id)

        if current is None:
            raise OrganisationError(
                f"organisation scope execution "
                f"{scope_execution_id} not found"
            )

        if current.state != "precondition_verified":
            raise OrganisationError(
                f"organisation scope execution "
                f"{scope_execution_id} is "
                f"'{current.state}'; only "
                f"'precondition_verified' executions may "
                f"claim their scope"
            )

        cursor = self.connection.cursor()

        try:
            cursor.execute(
                """
                UPDATE organisation_scope_executions
                SET state = 'executing',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND state = 'precondition_verified'
                """,
                (scope_execution_id,),
            )

            if cursor.rowcount != 1:
                self.connection.rollback()

                raise OrganisationError(
                    f"organisation scope execution "
                    f"{scope_execution_id} is no longer "
                    f"'precondition_verified'; cannot "
                    f"claim its scope"
                )

            cursor.execute(
                """
                DELETE FROM organisation_scope_claims
                WHERE scope_execution_id = ?
                """,
                (scope_execution_id,),
            )

            cursor.execute(
                """
                INSERT INTO organisation_scope_claims (
                    scope_execution_id, path, role
                ) VALUES (?, ?, 'source')
                """,
                (scope_execution_id, current.source_path),
            )

            cursor.execute(
                """
                INSERT INTO organisation_scope_claims (
                    scope_execution_id, path, role
                ) VALUES (?, ?, 'destination')
                """,
                (
                    scope_execution_id,
                    current.destination_path,
                ),
            )

            self._record_scope_execution_event(
                cursor,
                scope_execution_id=scope_execution_id,
                event_type="executing",
                previous_state=current.state,
                new_state="executing",
                actor="system",
                detail=(
                    "scope claimed (source + destination); "
                    "filesystem mutation authorised"
                ),
            )

            self.connection.commit()

        except sqlite3.IntegrityError as error:
            self.connection.rollback()

            raise OrganisationError(
                f"scope claim conflict for organisation "
                f"scope execution {scope_execution_id}: "
                f"{error}"
            ) from error

        return self.get_scope_execution(scope_execution_id)

    def create_scope_continuity(
        self,
        *,
        scope_execution_id: int,
        media_id: int,
        source_observation_id: int,
        result_observation_id: int,
    ) -> int:
        """
        Persist one execution-authorised continuity row for
        a single descendant of a scope execution. One row
        per descendant keeps every file independently
        attributable. No commit: the caller owns the
        transaction.
        """

        cursor = self.connection.cursor()

        cursor.execute(
            """
            INSERT INTO organisation_scope_continuity (
                scope_execution_id,
                media_id,
                source_observation_id,
                result_observation_id,
                authority
            )
            VALUES (?, ?, ?, ?, 'organisation_scope_execution')
            """,
            (
                scope_execution_id,
                media_id,
                source_observation_id,
                result_observation_id,
            ),
        )

        return cursor.lastrowid

    def scope_continuity_for(
        self,
        scope_execution_id: int,
    ) -> list:
        rows = self.connection.execute(
            """
            SELECT *
            FROM organisation_scope_continuity
            WHERE scope_execution_id = ?
            ORDER BY id
            """,
            (scope_execution_id,),
        ).fetchall()

        return [dict(row) for row in rows]

    # ---------------------------------------------------------
    # Sprint 15: metadata staleness
    # ---------------------------------------------------------

    def metadata_observation_freshness(
        self,
        observation_id: int,
    ) -> tuple:
        """
        Decide whether one cited metadata observation is still
        current: it exists, and no newer row for the same
        (media, provider, item) carries a different source
        fingerprint. Returns (True, "") or (False, reason).
        A newer row with an identical fingerprint means the
        provider was re-fetched without material change, so
        the citation stays current.
        """

        row = self.connection.execute(
            """
            SELECT media_id, provider, provider_item_id,
                   source_fingerprint
            FROM metadata_observations
            WHERE id = ?
            """,
            (observation_id,),
        ).fetchone()

        if row is None:
            return (
                False,
                f"metadata observation {observation_id} "
                f"no longer exists; re-plan",
            )

        media_id, provider, item_id, fingerprint = (
            row[0], row[1], row[2], row[3],
        )

        newer = self.connection.execute(
            """
            SELECT id, source_fingerprint
            FROM metadata_observations
            WHERE media_id = ?
              AND provider = ?
              AND provider_item_id = ?
              AND id > ?
            ORDER BY id DESC
            """,
            (media_id, provider, item_id, observation_id),
        ).fetchall()

        for _new_id, new_fingerprint in newer:
            if new_fingerprint != fingerprint:
                return (
                    False,
                    f"metadata observation "
                    f"{observation_id} is stale: provider "
                    f"'{provider}' item '{item_id}' was "
                    f"re-fetched with changed decision "
                    f"inputs; re-plan",
                )

        return (True, "")

def _assert_scope_execution_transition(
    current: str,
    new: str,
) -> None:
    """
    Scope executions share the per-file execution
    lifecycle vocabulary exactly: same states, same
    legal moves, same authority. Imported lazily so
    repository construction never depends on the
    execution models at import time.
    """

    from app.models.organisation_execution import (
        assert_transition,
    )

    assert_transition(current, new)
