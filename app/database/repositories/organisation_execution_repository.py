"""
Organisation execution persistence (Sprint 14).

Thin repository over the organisation_executions /
organisation_execution_events / organisation_execution_continuity
tables (migration 026). Rows are the durable, inspectable lifecycle
record of one approved organisation proposal being moved/renamed:

- created in state 'proposed' for an accepted proposal
- evolved ONLY through validated lifecycle transitions, each of
  which appends an immutable event row
- never deleted; a succeeded execution is the authoritative record
  of the filesystem operation
- proposal_id is UNIQUE so the same approved proposal can never be
  executed twice (idempotency / duplicate-execution protection)

Commit conventions mirror the other execution/recommendation
repositories: lifecycle transitions commit themselves; creation paths
leave the transaction to the caller.
"""

from __future__ import annotations

import json
import sqlite3

from app.models.organisation_execution import (
    TERMINAL_STATES,
    OrganisationExecutionRecord,
    assert_transition,
)


class OrganisationExecutionError(ValueError):
    """Raised for illegal organisation execution lifecycle operations."""


class ScopeClaimConflict(OrganisationExecutionError):
    """
    Raised when an execution cannot atomically claim its source and
    destination scope because another active execution already claims
    an overlapping path. The claim transaction is rolled back; no
    filesystem mutation may proceed.
    """


def canonical_path(path: str) -> str:
    """
    Canonical form used for scope-claim keys so that logically
    identical paths always collide atomically at the database.
    """

    import os

    return os.path.abspath(path)


class OrganisationExecutionRepository:

    def __init__(self, connection):

        self.connection = connection

    # ---------------------------------------------------------
    # creation
    # ---------------------------------------------------------

    def create(
        self,
        *,
        proposal_id: int,
        decision_run_id: int,
        media_id: int,
        intent: str,
        source_path: str,
        source_observation_id: int | None,
        source_size_bytes: int | None,
        source_mtime_ns: int | None,
        destination_path: str,
        actor: str = "human",
    ) -> int:
        """
        Create one execution in state 'proposed' for an accepted
        proposal. proposal_id is UNIQUE, so a second row for the same
        proposal raises an IntegrityError (duplicate execution guard).
        No commit: the caller owns the transaction.
        """

        cursor = self.connection.cursor()

        cursor.execute(
            """
            INSERT INTO organisation_executions (
                proposal_id,
                decision_run_id,
                media_id,
                intent,
                source_path,
                source_observation_id,
                source_size_bytes,
                source_mtime_ns,
                destination_path,
                state,
                actor,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'proposed',
                    ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (
                proposal_id,
                decision_run_id,
                media_id,
                intent,
                source_path,
                source_observation_id,
                source_size_bytes,
                source_mtime_ns,
                destination_path,
                actor,
            ),
        )

        execution_id = cursor.lastrowid

        self._record_event(
            cursor,
            execution_id=execution_id,
            event_type="proposed",
            previous_state=None,
            new_state="proposed",
            actor=actor,
            detail="execution record created for approved proposal",
        )

        self.connection.commit()

        return execution_id

    # ---------------------------------------------------------
    # reads
    # ---------------------------------------------------------

    def get(self, execution_id) -> OrganisationExecutionRecord | None:

        row = self.connection.execute(
            "SELECT * FROM organisation_executions WHERE id = ?",
            (execution_id,),
        ).fetchone()

        if row is None:

            return None

        return self._record_from_row(row)

    def get_by_proposal(
        self,
        proposal_id,
    ) -> OrganisationExecutionRecord | None:

        row = self.connection.execute(
            "SELECT * FROM organisation_executions "
            "WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()

        if row is None:

            return None

        return self._record_from_row(row)

    def list(self, limit=100) -> list[OrganisationExecutionRecord]:

        rows = self.connection.execute(
            "SELECT * FROM organisation_executions "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()

        return [self._record_from_row(row) for row in rows]

    def list_by_media(
        self,
        media_id,
    ) -> list[OrganisationExecutionRecord]:

        rows = self.connection.execute(
            "SELECT * FROM organisation_executions "
            "WHERE media_id = ? ORDER BY id DESC",
            (media_id,),
        ).fetchall()

        return [self._record_from_row(row) for row in rows]

    def list_active(
        self,
    ) -> list[OrganisationExecutionRecord]:
        """
        Non-terminal executions, oldest first. Used to detect
        same-source / same-destination / overlapping-scope conflicts
        across otherwise independent proposals.
        """

        rows = self.connection.execute(
            "SELECT * FROM organisation_executions "
            "WHERE state IN ("
            " 'proposed','approved','precondition_verified',"
            " 'executing','verifying','observation_persistence',"
            " 'provenance_persistence','interrupted',"
            " 'recovery_required'"
            ") ORDER BY id",
        ).fetchall()

        return [self._record_from_row(row) for row in rows]

    # ---------------------------------------------------------
    # scope claims (concurrency authority)
    # ---------------------------------------------------------

    def claim_scope(
        self,
        execution_id,
    ) -> OrganisationExecutionRecord:
        """
        Atomically claim the execution's source and destination paths
        and durably persist the EXECUTING lifecycle state in ONE
        transaction.

        This is the authoritative concurrency / serialization
        boundary: `organisation_execution_scopes.path` is UNIQUE, so a
        second execution claiming an overlapping path fails with
        ScopeClaimConflict here regardless of process interleaving.

        The filesystem mutation may only proceed after this call has
        committed. A crash at any later point leaves the durable state
        EXECUTING with the claims held, which recovery inspects.
        """

        current = self.get(execution_id)

        if current is None:

            raise OrganisationExecutionError(
                f"organisation execution {execution_id} not found"
            )

        if current.state != "precondition_verified":

            raise OrganisationExecutionError(
                f"organisation execution {execution_id} is "
                f"'{current.state}'; only 'precondition_verified' "
                f"executions may claim their scope"
            )

        source = canonical_path(current.source_path)

        destination = canonical_path(current.destination_path)

        if source == destination:

            raise OrganisationExecutionError(
                f"organisation execution {execution_id} source "
                f"equals destination; nothing to claim"
            )

        cursor = self.connection.cursor()

        try:

            # Guarded state transition: precondition_verified -> executing.
            cursor.execute(
                """
                UPDATE organisation_executions
                SET state = 'executing',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND state = 'precondition_verified'
                """,
                (execution_id,),
            )

            if cursor.rowcount != 1:

                self.connection.rollback()

                raise OrganisationExecutionError(
                    f"organisation execution {execution_id} is no "
                    f"longer 'precondition_verified'; cannot claim "
                    f"its scope"
                )

            # Idempotent re-claim: drop any stale self-claims (e.g.
            # after a reconciliation that returned the execution to a
            # retryable state) before re-inserting. The transaction
            # rolls back wholesale on any conflict, so a failed claim
            # restores this execution's prior claims.
            cursor.execute(
                """
                DELETE FROM organisation_execution_scopes
                WHERE execution_id = ?
                """,
                (execution_id,),
            )

            cursor.execute(
                """
                INSERT INTO organisation_execution_scopes (
                    execution_id, path, role
                ) VALUES (?, ?, 'source')
                """,
                (execution_id, source),
            )

            cursor.execute(
                """
                INSERT INTO organisation_execution_scopes (
                    execution_id, path, role
                ) VALUES (?, ?, 'destination')
                """,
                (execution_id, destination),
            )

            self._record_event(
                cursor,
                execution_id=execution_id,
                event_type="executing",
                previous_state=current.state,
                new_state="executing",
                actor=current.actor,
                detail=(
                    "execution scope claimed (source + destination); "
                    "filesystem mutation authorised"
                ),
            )

            self.connection.commit()

        except sqlite3.IntegrityError as error:

            self.connection.rollback()

            raise ScopeClaimConflict(
                f"execution scope conflict for organisation execution "
                f"{execution_id}: {source} -> {destination} overlaps "
                f"an active execution claim: {error}"
            ) from error

        return self.get(execution_id)

    def release_scope(self, execution_id) -> None:
        """
        Release the execution's scope claims. Invoked when an
        execution reaches a terminal state so its paths become
        claimable by future executions.
        """

        self.connection.execute(
            "DELETE FROM organisation_execution_scopes "
            "WHERE execution_id = ?",
            (execution_id,),
        )

    def scopes_for(self, execution_id) -> list[dict]:

        rows = self.connection.execute(
            """
            SELECT path, role, created_at
            FROM organisation_execution_scopes
            WHERE execution_id = ?
            ORDER BY id
            """,
            (execution_id,),
        ).fetchall()

        return [
            {
                "path": row[0],
                "role": row[1],
                "created_at": row[2],
            }
            for row in rows
        ]

    def has_scope(self, execution_id) -> bool:

        row = self.connection.execute(
            "SELECT 1 FROM organisation_execution_scopes "
            "WHERE execution_id = ? LIMIT 1",
            (execution_id,),
        ).fetchone()

        return row is not None

    # ---------------------------------------------------------
    # lifecycle transitions
    # ---------------------------------------------------------

    def update_state(
        self,
        execution_id,
        *,
        state,
        error=None,
        result_observation_id=None,
        continuity_id=None,
        clear_error=False,
    ) -> OrganisationExecutionRecord:
        """
        Advance the state machine. Only provided fields change;
        everything previously recorded is preserved as history.
        Transitions are validated against the explicit lifecycle.

        When the new state is terminal (SUCCEEDED / FAILED) the
        execution's scope claims are released in the same transaction,
        making its source/destination paths claimable again.
        """

        current = self.get(execution_id)

        if current is None:

            raise OrganisationExecutionError(
                f"organisation execution {execution_id} not found"
            )

        assert_transition(current.state, state)

        assignments = [
            "state = ?",
            "updated_at = CURRENT_TIMESTAMP",
        ]

        values = [state]

        for column, value in [
            ("error", error),
            ("result_observation_id", result_observation_id),
            ("continuity_id", continuity_id),
        ]:

            if value is not None:

                assignments.append(f"{column} = ?")

                values.append(value)

        if clear_error:

            assignments.append("error = NULL")

        values.append(execution_id)

        self.connection.execute(
            f"""
            UPDATE organisation_executions SET
                {", ".join(assignments)}
            WHERE id = ?
            """,
            tuple(values),
        )

        self._record_event(
            self.connection.cursor(),
            execution_id=execution_id,
            event_type=state,
            previous_state=current.state,
            new_state=state,
            actor=current.actor,
            detail=error,
        )

        if state in TERMINAL_STATES:

            self.release_scope(execution_id)

        self.connection.commit()

        return self.get(execution_id)

    def events_for(self, execution_id) -> list[dict]:

        rows = self.connection.execute(
            """
            SELECT
                event_type,
                previous_state,
                new_state,
                actor,
                detail,
                created_at
            FROM organisation_execution_events
            WHERE execution_id = ?
            ORDER BY id
            """,
            (execution_id,),
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
    # continuity
    # ---------------------------------------------------------

    def create_continuity(
        self,
        *,
        execution_id,
        media_id,
        source_observation_id,
        result_observation_id,
    ) -> int:
        """
        Persist the explicit execution-authorised identity-continuity
        relationship between the source observation and the resulting
        observation of the SAME media identity, naming this execution
        as the authority. No commit: the caller owns the transaction.
        """

        cursor = self.connection.cursor()

        cursor.execute(
            """
            INSERT INTO organisation_execution_continuity (
                execution_id,
                media_id,
                source_observation_id,
                result_observation_id,
                authority
            )
            VALUES (?, ?, ?, ?, 'organisation_execution')
            """,
            (
                execution_id,
                media_id,
                source_observation_id,
                result_observation_id,
            ),
        )

        return cursor.lastrowid

    def continuity_for(self, execution_id):

        rows = self.connection.execute(
            "SELECT * FROM organisation_execution_continuity "
            "WHERE execution_id = ? ORDER BY id",
            (execution_id,),
        ).fetchall()

        return [
            {
                "id": row[0],
                "execution_id": row[1],
                "media_id": row[2],
                "source_observation_id": row[3],
                "result_observation_id": row[4],
                "authority": row[5],
                "created_at": row[6],
            }
            for row in rows
        ]

    # ---------------------------------------------------------
    # internals
    # ---------------------------------------------------------

    @staticmethod
    def _record_event(
        cursor,
        *,
        execution_id,
        event_type,
        previous_state,
        new_state,
        actor,
        detail,
    ) -> None:

        cursor.execute(
            """
            INSERT INTO organisation_execution_events (
                execution_id,
                event_type,
                previous_state,
                new_state,
                actor,
                detail
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                execution_id,
                event_type,
                previous_state,
                new_state,
                actor,
                detail,
            ),
        )

    def _record_from_row(
        self,
        row,
    ) -> OrganisationExecutionRecord:

        return OrganisationExecutionRecord(
            id=row[0],
            proposal_id=row[1],
            decision_run_id=row[2],
            media_id=row[3],
            intent=row[4],
            source_path=row[5],
            source_observation_id=row[6],
            source_size_bytes=row[7],
            source_mtime_ns=row[8],
            destination_path=row[9],
            state=row[10],
            error=row[11],
            result_observation_id=row[12],
            continuity_id=row[13],
            actor=row[14],
            created_at=row[15],
            updated_at=row[16],
        )
