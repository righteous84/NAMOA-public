"""
Execution job persistence (Sprint 9, extended Phase 6).

Thin repository over the media_executions table (migration 023, with
Phase 6 migrations 032 and 033). Rows are the durable, inspectable
approval/execution lifecycle record: created on explicit approval,
evolved through the state machine, never deleted (history is
preserved, including failures).

Phase 6 additions:

- requested_transformation_json / predicted_json / measured_json /
  verification_json (migration 032)
- source_observation_id / delete_original_requested / deletion_state /
  original_deleted_at (migration 033)
"""

import json

from app.models.execution import (
    ExecutionJob,
    assert_transition,
)


class ExecutionRepository:

    def __init__(self, connection):

        self.connection = connection

    def create(
        self,
        *,
        media_id,
        opportunity,
        analysis_run_id,
        source_path,
        source_size_bytes,
        source_mtime_ns,
        source_inode,
        approved_by,
        source_sha256=None,
        source_observation_id=None,
        requested_transformation=None,
        delete_original_requested=False,
    ):
        """
        Create one job in state 'approved'. Returns the job id.
        """

        cursor = self.connection.cursor()

        cursor.execute(
            """
            INSERT INTO media_executions (
                media_id,
                opportunity,
                analysis_run_id,
                source_path,
                source_size_bytes,
                source_mtime_ns,
                source_inode,
                source_sha256,
                approved_by,
                approved_at,
                source_observation_id,
                requested_transformation_json,
                delete_original_requested,
                state,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'approved',
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (
                media_id,
                opportunity,
                analysis_run_id,
                source_path,
                source_size_bytes,
                source_mtime_ns,
                source_inode,
                source_sha256,
                approved_by,
                _now(),
                source_observation_id,
                _dump_json(requested_transformation),
                1 if delete_original_requested else 0,
            ),
        )

        self.connection.commit()

        return cursor.lastrowid

    def get(self, job_id) -> ExecutionJob | None:

        row = self.connection.execute(
            "SELECT * FROM media_executions WHERE id = ?",
            (job_id,),
        ).fetchone()

        if row is None:

            return None

        return self._job_from_row(row)

    def attach_recommendation(
        self,
        job_id,
        recommendation_id,
    ):
        """
        Record the durable link from an execution job to the
        recommendation that was accepted (Sprint 10 correction).
        Purely a linkage write; execution state remains untouched.
        """

        cursor = self.connection.cursor()

        cursor.execute(
            """
            UPDATE media_executions
            SET recommendation_id = ?
            WHERE id = ?
            """,
            (recommendation_id, job_id),
        )

        self.connection.commit()

    def list(self, limit=100):

        rows = self.connection.execute(
            """
            SELECT * FROM media_executions
            ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()

        return [self._job_from_row(row) for row in rows]

    def list_by_media(self, media_id):
        """
        Every execution job recorded for one lineage, newest first.
        Persistence read only: rows are the durable outcome history
        and are returned exactly as stored.
        """

        rows = self.connection.execute(
            """
            SELECT * FROM media_executions
            WHERE media_id = ?
            ORDER BY id DESC
            """,
            (media_id,),
        ).fetchall()

        return [self._job_from_row(row) for row in rows]

    def list_active_for_media(self, media_id):
        """
        Non-terminal jobs for one lineage, oldest first. Used by the
        approval boundary to refuse queueing the same recommendation
        twice while a job is still actionable.
        """

        rows = self.connection.execute(
            """
            SELECT * FROM media_executions
            WHERE media_id = ?
              AND state IN (
                'approved', 'planned', 'running',
                'verifying', 'replacing', 'deleting_original'
              )
            ORDER BY id
            """,
            (media_id,),
        ).fetchall()

        return [self._job_from_row(row) for row in rows]

    def completed_media_ids(self) -> set:
        """
        Logical media items with at least one successfully completed
        execution. Read-only: `succeeded` is the authoritative
        optimistic-execution completion state, never inferred from
        approval, preference acceptance, or recommendation existence.
        """

        rows = self.connection.execute(
            """
            SELECT DISTINCT media_id FROM media_executions
            WHERE state = 'succeeded'
            """
        ).fetchall()

        return {row[0] for row in rows}

    def active_media_ids(self) -> set:
        """
        Logical media items with a non-terminal execution in
        progress. Read-only aggregation; execution state remains the
        single authority.
        """

        rows = self.connection.execute(
            """
            SELECT DISTINCT media_id FROM media_executions
            WHERE state IN (
                'approved', 'planned', 'running',
                'verifying', 'replacing', 'deleting_original',
                'interrupted'
            )
            """
        ).fetchall()

        return {row[0] for row in rows}

    def list_queueable(self):
        """
        Jobs the queue worker may process, oldest first: approved or
        planned jobs only. The worker never invents work; it executes
        exactly what approval and planning already recorded.
        """

        rows = self.connection.execute(
            """
            SELECT * FROM media_executions
            WHERE state IN ('approved', 'planned')
            ORDER BY id
            """,
        ).fetchall()

        return [self._job_from_row(row) for row in rows]

    def list_recoverable(self):
        """
        Jobs in an active/non-terminal state that recovery should
        resolve before any new work runs (interrupted, running,
        verifying, replacing, deleting_original). Read by the queue
        worker on start so application restart never silently loses
        execution state and never duplicates an execution.
        """

        rows = self.connection.execute(
            """
            SELECT * FROM media_executions
            WHERE state IN (
                'interrupted', 'running', 'verifying', 'replacing',
                'deleting_original'
            )
            ORDER BY id
            """,
        ).fetchall()

        return [self._job_from_row(row) for row in rows]

    def update_plan(
        self,
        job_id,
        *,
        plan,
        policy_decision,
        state,
        predicted=None,
    ):
        """
        Persist the frozen plan and policy decision together with a
        state transition. Transitions are validated against the
        explicit lifecycle; illegal moves raise ValueError.

        `predicted` is the predicted-savings snapshot (migration 032).
        """

        current = self.get(job_id)

        if current is None:

            raise ValueError(
                f"execution job {job_id} not found"
            )

        assert_transition(current.state, state)

        self.connection.execute(
            """
            UPDATE media_executions SET
                plan_json = ?,
                policy_json = ?,
                predicted_json = ?,
                state = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                json.dumps(plan, indent=2),
                json.dumps(policy_decision, indent=2),
                _dump_json(predicted),
                state,
                job_id,
            ),
        )

        self.connection.commit()

    def update_state(
        self,
        job_id,
        *,
        state,
        error=None,
        temp_output_path=None,
        backup_path=None,
        output_sha256=None,
        result_observation_id=None,
        measured=None,
        verification=None,
        deletion_state=None,
        original_deleted_at=None,
    ):
        """
        Advance the state machine. Only provided fields change;
        everything previously recorded is preserved as history.

        Transitions are validated against the explicit lifecycle;
        illegal moves (for example succeeded -> running or failed ->
        approved) raise ValueError instead of silently mutating the
        record.
        """

        current = self.get(job_id)

        if current is None:

            raise ValueError(
                f"execution job {job_id} not found"
            )

        assert_transition(current.state, state)

        assignments = [
            "state = ?",
            "updated_at = CURRENT_TIMESTAMP",
        ]

        values = [state]

        for column, value in [
            ("error", error),
            ("temp_output_path", temp_output_path),
            ("backup_path", backup_path),
            ("output_sha256", output_sha256),
            ("result_observation_id", result_observation_id),
            ("measured_json", _dump_json(measured)),
            ("verification_json", _dump_json(verification)),
            ("deletion_state", deletion_state),
            ("original_deleted_at", original_deleted_at),
        ]:

            if value is not None:

                assignments.append(f"{column} = ?")

                values.append(value)

        values.append(job_id)

        self.connection.execute(
            f"""
            UPDATE media_executions SET
                {", ".join(assignments)}
            WHERE id = ?
            """,
            tuple(values),
        )

        self.connection.commit()

    def _job_from_row(self, row) -> ExecutionJob:

        plan = _safe_load(row["plan_json"])

        policy = _safe_load(row["policy_json"])

        return ExecutionJob(
            id=row["id"],
            media_id=row["media_id"],
            opportunity=row["opportunity"],
            analysis_run_id=row["analysis_run_id"],
            source_path=row["source_path"],
            source_size_bytes=row["source_size_bytes"],
            source_mtime_ns=row["source_mtime_ns"],
            source_inode=row["source_inode"],
            source_sha256=row["source_sha256"],
            approved_by=row["approved_by"],
            state=row["state"],
            plan=plan or {},
            policy_decision=policy or {},
            backup_path=row["backup_path"],
            temp_output_path=row["temp_output_path"],
            output_sha256=row["output_sha256"],
            result_observation_id=row[
                "result_observation_id"
            ],
            recommendation_id=row["recommendation_id"],
            source_observation_id=row[
                "source_observation_id"
            ],
            delete_original_requested=bool(
                row["delete_original_requested"]
            ),
            deletion_state=row["deletion_state"],
            original_deleted_at=row["original_deleted_at"],
            requested_transformation=_safe_load(
                row["requested_transformation_json"]
            ) or {},
            predicted=_safe_load(row["predicted_json"]) or {},
            measured=_safe_load(row["measured_json"]) or {},
            verification=_safe_load(
                row["verification_json"]
            ) or {},
            error=row["error"],
        )


def _safe_load(payload):

    if not payload:

        return None

    try:

        return json.loads(payload)

    except json.JSONDecodeError:

        return None


def _dump_json(value):

    if value is None:

        return None

    if isinstance(value, dict):

        return json.dumps(value, indent=2)

    return value


def _now():

    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )