"""
Organisation execution application service (Sprint 14).

The single operational authority for executing an APPROVED
organisation proposal as a safe, deterministic move/rename. External
interfaces (CLI/GUI/API) may only execute and recover through this
service; they never touch the filesystem themselves.

Lifecycle and safety model:

    approved organisation proposal (Sprint 13, state 'accepted')
        ↓  execute(proposal_id, actor): explicit human action
    execution 'proposed'
        ↓  approval revalidated, execution authority established
    execution 'approved'
        ↓  deterministic filesystem preconditions revalidated
    execution 'precondition_verified'
        ↓  scope claimed + EXECUTING durably persisted (atomic claim:
        ↓  UNIQUE source/destination rows = authoritative
        ↓  concurrency/serialization boundary)
    execution 'executing'
        ↓  safe move/rename (after the claim committed)
    execution 'verifying'  (persisted after mutation, before verifying)
        ↓  postcondition verified against real filesystem reality
    execution 'observation_persistence'
        ↓  resulting observation recorded for the SAME media_id
    execution 'provenance_persistence'
        ↓  execution-authorised identity continuity + provenance
    execution 'succeeded'

Guarantees enforced here:

- a proposal alone can never execute: the proposal must be in the
  durable 'accepted' (approved) state and approval must remain valid
- an already-executed proposal cannot execute twice (proposal_id is
  UNIQUE; a succeeded/failed execution refuses)
- execution-time preconditions are revalidated immediately before
  claiming the execution scope (source exists, unchanged, within
  boundary; destination valid, within boundary, no collision; no
  stale source state)
- concurrency is NOT check-then-act: execution authority is claimed
  atomically at the database (UNIQUE scope rows for source and
  destination) in the same transaction that persists EXECUTING; a
  conflicting claim fails regardless of process interleaving and no
  filesystem mutation occurs
- the filesystem safety boundary is deterministic and code-enforced
  (never an AI decision)
- a successful filesystem API call is NOT success: postconditions are
  verified against real filesystem reality before SUCCEEDED
- collisions and overwrites are never silently resolved
- uncertainty after interruption becomes RECOVERY_REQUIRED and is
  reconciled by inspecting actual filesystem reality, never guessed;
  finalisation is idempotent so recovery never creates duplicate
  observations, continuity, or provenance
- identity continuity is execution-authorised and explicit
"""

import os

from app.execution.organisation_safety import (
    OrganisationSafetyError,
    canonical,
    ensure_destination_parent,
    subtree_file_manifest,
    validate_destination,
    validate_directory_destination,
    validate_directory_source,
    validate_source,
)

from app.execution.engine import sha256_of

from app.database.repositories.organisation_execution_repository import (
    ScopeClaimConflict,
)

from app.models.organisation import (
    INTENT_MOVE_DESTINATION,
    INTENT_RENAME,
    SCOPE_ACTION_DIRECTORY_CREATION,
    SCOPE_ACTION_DIRECTORY_MOVE,
    SCOPE_ACTION_DIRECTORY_RENAME,
    SCOPE_ACTION_SUBTREE_RELOCATION,
)

from app.models.organisation_execution import (
    STATE_APPROVED,
    STATE_EXECUTING,
    STATE_FAILED,
    STATE_INTERRUPTED,
    STATE_OBSERVATION_PERSISTENCE,
    STATE_PRECONDITION_VERIFIED,
    STATE_PROPOSED,
    STATE_PROVENANCE_PERSISTENCE,
    STATE_RECOVERY_REQUIRED,
    STATE_SUCCEEDED,
    STATE_VERIFYING,
)

# States that can be driven to completion by execute(): they have not
# yet claimed their scope, so no authority boundary has been crossed.
DRIVABLE_STATES = frozenset(
    {
        STATE_PROPOSED,
        STATE_APPROVED,
    }
)

# States that may require recovery: the execution may be anywhere
# after the scope claim / mutation / persistence boundaries.
RECOVERABLE_STATES = frozenset(
    {
        STATE_PRECONDITION_VERIFIED,
        STATE_EXECUTING,
        STATE_VERIFYING,
        STATE_OBSERVATION_PERSISTENCE,
        STATE_PROVENANCE_PERSISTENCE,
        STATE_INTERRUPTED,
        STATE_RECOVERY_REQUIRED,
    }
)


def _devices_differ(source, destination) -> bool:
    """
    True when source and destination demonstrably live
    on different filesystems: compare the source device
    against the nearest existing ancestor of the
    destination directory. False when either side
    cannot be stated. Read-only.
    """

    try:
        source_device = os.stat(source).st_dev
    except OSError:
        return False

    target = os.path.dirname(os.path.abspath(destination or ""))

    while target and not os.path.exists(target):
        parent = os.path.dirname(target)

        if parent == target:
            break

        target = parent

    if not target or not os.path.exists(target):
        return False

    try:
        return os.stat(target).st_dev != source_device
    except OSError:
        return False


class OrganisationExecutionService:

    def __init__(
        self,
        *,
        execution_repository,
        organisation_repository,
        media_repository,
        notification_service=None,
    ):

        self.executions = execution_repository

        self.organisation_records = organisation_repository

        self.media_repository = media_repository

        self.notification_service = notification_service

    def _notify(
        self,
        category: str,
        title: str,
        message: str,
        *,
        media_id=None,
    ):
        """
        Best-effort notification emission. A notification write must
        never fail or alter the organisation execution operation.
        """

        if self.notification_service is None:
            return

        try:

            self.notification_service.create(
                category=category,
                title=title,
                message=message,
                media_id=media_id,
            )

        except Exception:

            from app.utils.logger import logger

            logger.warning(
                "notification write skipped (best-effort): "
                f"{category} {title}"
            )

    # ---------------------------------------------------------
    # public workflows
    # ---------------------------------------------------------

    def execute(
        self,
        proposal_id,
        *,
        actor: str = "human",
    ):
        """
        Execute one approved organisation proposal through the full
        safe sequence. Returns the final execution record.

        Idempotency: if an execution already exists for this proposal
        it is reconciled first (recovery) or refused (already
        succeeded / known failure / active).
        """

        proposal = self._require_accepted_proposal(proposal_id)

        self._assert_metadata_current(proposal)

        execution = self.executions.get_by_proposal(proposal_id)

        if execution is not None:

            if execution.state == STATE_SUCCEEDED:

                raise ValueError(
                    f"organisation proposal {proposal_id} has "
                    f"already been executed (execution "
                    f"{execution.id}); it will not be moved again"
                )

            if execution.state == STATE_FAILED:

                raise ValueError(
                    f"organisation proposal {proposal_id} failed "
                    f"to execute (execution {execution.id}); "
                    f"re-approve or raise a new proposal"
                )

            if execution.state in RECOVERABLE_STATES:

                self._reconcile(execution)

                execution = self.executions.get(execution.id)

            if execution.state not in DRIVABLE_STATES:

                raise ValueError(
                    f"organisation proposal {proposal_id} "
                    f"requires manual reconciliation "
                    f"(execution {execution.id}); it is "
                    f"'{execution.state}'"
                )

        if execution is None:

            execution_id = self.executions.create(
                proposal_id=proposal.id,
                decision_run_id=proposal.decision_run_id,
                media_id=proposal.media_id,
                intent=proposal.intent,
                source_path=self._source_path(proposal),
                source_observation_id=self._source_observation_id(
                    proposal
                ),
                source_size_bytes=self._source_observation(
                    proposal
                ).size_bytes,
                source_mtime_ns=self._source_observation(
                    proposal
                ).file_mtime_ns,
                destination_path=self._destination_path(proposal),
                actor=actor,
            )

            execution = self.executions.get(execution_id)

        return self._drive(execution, proposal)

    def recover(self, execution_id, *, actor: str = "system"):
        """
        Reconcile an execution that may be interrupted anywhere after
        the scope claim / mutation / persistence boundaries by
        inspecting actual filesystem reality (never the persisted
        state alone). Returns the updated execution record.
        """

        execution = self._get(execution_id)

        if execution.state not in RECOVERABLE_STATES:

            raise ValueError(
                f"organisation execution {execution_id} is "
                f"'{execution.state}'; nothing to recover"
            )

        self._reconcile(execution)

        return self.executions.get(execution_id)

    # ---------------------------------------------------------
    # reads
    # ---------------------------------------------------------

    def get(self, execution_id):

        return self._get(execution_id)

    def get_by_proposal(self, proposal_id):

        return self.executions.get_by_proposal(proposal_id)

    def list(self, limit=100):

        return self.executions.list(limit)

    def list_by_media(self, media_id):

        return self.executions.list_by_media(media_id)

    def events(self, execution_id):

        return self.executions.events_for(execution_id)

    def continuity(self, execution_id):

        return self.executions.continuity_for(execution_id)

    # ---------------------------------------------------------
    # proposal context
    # ---------------------------------------------------------

    def _require_accepted_proposal(self, proposal_id):

        proposal = self.organisation_records.get_proposal(
            proposal_id
        )

        if proposal is None:

            raise ValueError(
                f"organisation proposal {proposal_id} not found"
            )

        if proposal.state != "accepted":

            raise ValueError(
                f"organisation proposal {proposal_id} is "
                f"'{proposal.state}'; only approved ('accepted') "
                f"proposals may execute"
            )

        if proposal.intent not in (
            INTENT_MOVE_DESTINATION,
            INTENT_RENAME,
        ):

            raise ValueError(
                f"organisation proposal {proposal_id} has intent "
                f"'{proposal.intent}'; only move_destination and "
                f"rename are executable organisation operations"
            )

        return proposal

    def _source_path(self, proposal) -> str:

        source = (proposal.evidence or {}).get("current_path")

        if not source:

            raise ValueError(
                f"organisation proposal {proposal.id} has no "
                f"source path evidence; cannot execute"
            )

        return str(source)

    def _source_observation(self, proposal):
        """
        The exact filesystem observation the proposal cited as its
        source context. This is the authoritative source-state
        evidence; execution compares live reality against it.
        """

        observation_id = self._source_observation_id(proposal)

        observation = self.media_repository.get_observation_by_id(
            observation_id
        )

        if observation is None:

            raise ValueError(
                f"organisation proposal {proposal.id} cites source "
                f"observation {observation_id} which no longer exists"
            )

        return observation

    def _source_observation_id(self, proposal):

        observation_id = (proposal.evidence or {}).get(
            "observation_id"
        )

        if observation_id is None:

            raise ValueError(
                f"organisation proposal {proposal.id} cites no "
                f"source observation; cannot execute"
            )

        return int(observation_id)

    def _destination_path(self, proposal) -> str:

        if proposal.intent == INTENT_MOVE_DESTINATION:

            destination = proposal.proposed_destination

            if not destination:

                raise ValueError(
                    f"organisation proposal {proposal.id} is a "
                    f"move but has no proposed destination"
                )

            return str(destination)

        # rename: stays in the same directory under the proposed name
        name = proposal.proposed_name

        if not name:

            raise ValueError(
                f"organisation proposal {proposal.id} is a rename "
                f"but has no proposed name"
            )

        source = self._source_path(proposal)

        return os.path.join(os.path.dirname(source), name)

    def _library_roots(self, proposal) -> list:

        run = self.organisation_records.get_decision_run(
            proposal.decision_run_id
        )

        if run is None:

            raise ValueError(
                f"organisation decision run "
                f"{proposal.decision_run_id} not found"
            )

        return list(run.library_roots)

    def _notify_execution(self, execution):
        """
        Best-effort notification for an organisation execution
        outcome, derived from the durable execution state.
        """

        if self.notification_service is None:
            return

        media_id = execution.media_id

        destination = execution.destination_path

        if execution.state == STATE_SUCCEEDED:

            self._notify(
                "success",
                "Organisation change complete",
                f"media {media_id} moved to {destination} · "
                "verified and recorded",
                media_id=media_id,
            )

        elif execution.state == STATE_FAILED:

            self._notify(
                "error",
                "Organisation change failed",
                f"media {media_id} · {execution.error or 'execution failed'}",
                media_id=media_id,
            )

        elif execution.state in (
            STATE_RECOVERY_REQUIRED,
            STATE_INTERRUPTED,
        ):

            self._notify(
                "attention",
                "Organisation change needs recovery",
                f"media {media_id} · {execution.error or 'filesystem state is uncertain'}",
                media_id=media_id,
            )

    # ---------------------------------------------------------
    # execution drive
    # ---------------------------------------------------------

    def _drive(self, execution, proposal):
        """
        Drive an execution through the full safe lifecycle to
        SUCCEEDED or an honest failure/recovery state.

        Execution ordering (Correction 1): the EXECUTING lifecycle
        state is durably persisted (together with the scope claims)
        BEFORE any filesystem mutation, and VERIFYING is durably
        persisted AFTER the mutation but BEFORE postcondition
        verification. Recovery can therefore determine from durable
        state alone that filesystem mutation was in progress.
        """

        roots = self._library_roots(proposal)

        execution_id = execution.id

        if execution.state == STATE_PROPOSED:

            self.executions.update_state(
                execution_id,
                state=STATE_APPROVED,
                error=None,
            )

        # --- precondition verification ------------------------
        try:

            self._verify_preconditions(execution, proposal, roots)

        except (OrganisationSafetyError, ValueError) as error:

            self.executions.update_state(
                execution_id,
                state=STATE_FAILED,
                error=str(error),
            )

            current = self.executions.get(execution_id)

            self._notify_execution(current)

            return current

        self.executions.update_state(
            execution_id,
            state=STATE_PRECONDITION_VERIFIED,
        )

        # --- claim scope + persist EXECUTING (authority boundary) --
        # Atomically claims source+destination (UNIQUE scope rows) and
        # durably persists EXECUTING in one transaction. If exclusive
        # authority cannot be established, no filesystem mutation
        # occurs.
        try:

            self.executions.claim_scope(execution_id)

        except ScopeClaimConflict as error:

            self.executions.update_state(
                execution_id,
                state=STATE_FAILED,
                error=str(error),
            )

            current = self.executions.get(execution_id)

            self._notify_execution(current)

            return current

        # --- filesystem mutation --------------------------------
        # Only after EXECUTING is durably persisted and the scope is
        # claimed.
        source = canonical(execution.source_path)

        destination = canonical(execution.destination_path)

        try:

            ensure_destination_parent(destination)

            if _devices_differ(source, destination):
                self._mutate_copy_verify_delete(
                    source, destination, proposal
                )
            else:
                os.rename(source, destination)

        except OSError as error:

            # os.rename is atomic: an exception means the move did
            # not happen. Known no-uncertainty failure.
            self.executions.update_state(
                execution_id,
                state=STATE_FAILED,
                error=f"move failed: {error}",
            )

            current = self.executions.get(execution_id)

            self._notify_execution(current)

            return current

        # --- persist VERIFYING, then verify ----------------------
        self.executions.update_state(
            execution_id,
            state=STATE_VERIFYING,
        )

        try:

            self._verify_postconditions(execution, proposal, roots)

        except OrganisationSafetyError as error:

            # The move happened but cannot be verified -> uncertain.
            self.executions.update_state(
                execution_id,
                state=STATE_RECOVERY_REQUIRED,
                error=str(error),
            )

            current = self.executions.get(execution_id)

            self._notify_execution(current)

            return current

        return self._finalise(execution, proposal)

    def _mutate_copy_verify_delete(
        self, source, destination, proposal
    ) -> None:
        """
        Cross-filesystem mutation: copy, verify the copy
        against source-state evidence, then remove the
        source. The source is never deleted before the
        destination is proven good; a failed copy removes
        the partial destination and leaves the source
        untouched. Raises OrganisationSafetyError (fails
        the execution, source preserved) or OSError.
        """

        import shutil

        source_stat = os.stat(source)

        try:
            shutil.copy2(source, destination)
        except OSError as error:
            self._remove_partial(destination)

            raise OrganisationSafetyError(
                f"cross-filesystem copy failed: {error}; "
                f"source preserved"
            ) from error

        try:
            dest_stat = os.stat(destination)
        except OSError as error:
            self._remove_partial(destination)

            raise OrganisationSafetyError(
                f"cross-filesystem copy unverifiable: "
                f"{error}; source preserved"
            ) from error

        if (
            dest_stat.st_size != source_stat.st_size
            or dest_stat.st_mtime_ns
            != source_stat.st_mtime_ns
        ):
            self._remove_partial(destination)

            raise OrganisationSafetyError(
                "cross-filesystem copy verification failed "
                "(size/mtime mismatch); partial destination "
                "removed, source preserved"
            )

        source_observation = self._source_observation(
            proposal
        )
        expected_hash = (
            source_observation.sha256_hash
            if source_observation is not None
            else None
        )

        if expected_hash:
            live_hash = sha256_of(destination)

            if live_hash != expected_hash:
                self._remove_partial(destination)

                raise OrganisationSafetyError(
                    "cross-filesystem copy verification "
                    "failed (content hash mismatch); "
                    "partial destination removed, source "
                    "preserved"
                )

        try:
            os.unlink(source)
        except OSError as error:
            raise OrganisationSafetyError(
                f"destination verified but source removal "
                f"failed: {error}; both copies exist, "
                f"recovery required"
            ) from error

    @staticmethod
    def _remove_partial(path) -> None:
        """Best-effort removal of a partial destination."""

        try:
            if os.path.isfile(path) and not os.path.islink(
                path
            ):
                os.unlink(path)
        except OSError:
            pass

    def _verify_preconditions(self, execution, proposal, roots) -> None:
        """
        Deterministic execution-time preconditions, revalidated
        immediately before filesystem mutation.
        """

        source = execution.source_path

        destination = execution.destination_path

        # Source exists, regular file, not a symlink, inside boundary.
        stat = validate_source(source, roots)

        # Source still the authorised observation context / lineage.
        lineage = self.media_repository.get_media_item(
            proposal.media_id
        )

        if lineage is None or lineage.status != "active":

            raise OrganisationSafetyError(
                f"media lineage {proposal.media_id} is not active; "
                f"the source is no longer the authorised observation "
                f"context"
            )

        if canonical(lineage.file_path) != canonical(source):

            raise OrganisationSafetyError(
                f"source path {source} no longer matches the media "
                f"lineage's current path {lineage.file_path}; "
                f"the source has moved outside NAMOA"
            )

        source_observation = self._source_observation(proposal)

        if (
            stat.st_size != source_observation.size_bytes
            or stat.st_mtime_ns != source_observation.file_mtime_ns
        ):

            raise OrganisationSafetyError(
                f"source has changed since the authorised proposal "
                f"was generated "
                f"(expected {source_observation.size_bytes}/"
                f"{source_observation.file_mtime_ns}, "
                f"now {stat.st_size}/{stat.st_mtime_ns}); "
                f"re-scan and generate a fresh proposal"
            )

        # Destination: inside boundary, no unsafe symlink, no object.
        validate_destination(destination, roots, must_be_absent=True)

        if canonical(source) == canonical(destination):

            raise OrganisationSafetyError(
                f"destination equals source; nothing to organise: "
                f"{destination}"
            )

        # Destination must not already be owned by another lineage.
        self._assert_no_destination_lineage(
            proposal.media_id, destination
        )

    def _verify_postconditions(self, execution, proposal, roots) -> None:
        """
        Verify actual filesystem reality after the mutation. A
        successful rename() alone never establishes success.

        The destination must match the recorded source observation's
        currentness evidence used by NAMOA identity/currentness:

            size_bytes + file_mtime_ns

        A recorded SHA-256 hash is additionally verified when present;
        a missing hash never relaxes the size + mtime requirements.
        """

        source = execution.source_path

        destination = execution.destination_path

        if not os.path.lexists(destination):

            raise OrganisationSafetyError(
                f"postcondition failed: expected destination "
                f"does not exist: {destination}"
            )

        if os.path.lexists(source):

            raise OrganisationSafetyError(
                f"postcondition failed: source is still present: "
                f"{source}"
            )

        if os.path.islink(destination):

            raise OrganisationSafetyError(
                f"postcondition failed: destination is a symlink: "
                f"{destination}"
            )

        if not os.path.isfile(destination):

            raise OrganisationSafetyError(
                f"postcondition failed: destination is not a "
                f"regular file: {destination}"
            )

        if not (
            os.path.isdir(os.path.dirname(canonical(destination)))
        ):

            raise OrganisationSafetyError(
                f"postcondition failed: destination parent is not "
                f"a directory"
            )

        stat = os.stat(destination)

        expected_size = execution.source_size_bytes

        if expected_size is not None and stat.st_size != expected_size:

            raise OrganisationSafetyError(
                f"postcondition failed: destination size "
                f"{stat.st_size} does not match the expected "
                f"source-state evidence {expected_size}"
            )

        source_observation = self._source_observation(proposal)

        expected_mtime_ns = source_observation.file_mtime_ns

        if (
            expected_mtime_ns is not None
            and stat.st_mtime_ns != expected_mtime_ns
        ):

            raise OrganisationSafetyError(
                f"postcondition failed: destination mtime "
                f"{stat.st_mtime_ns} does not match the expected "
                f"source-state evidence {expected_mtime_ns}"
            )

        expected_hash = source_observation.sha256_hash

        if expected_hash:

            live_hash = sha256_of(destination)

            if live_hash != expected_hash:

                raise OrganisationSafetyError(
                    f"postcondition failed: destination content hash "
                    f"does not match the recorded source-state "
                    f"evidence"
                )

    def _finalise(self, execution, proposal):
        """
        After successful postcondition verification, persist the
        resulting observation for the SAME media_id, the explicit
        execution-authorised continuity, and provenance, then reach
        SUCCEEDED.

        Fully idempotent: if the resulting observation or continuity
        already exist (a prior partial run survived), they are reused;
        no duplicate observation, continuity or provenance is created.
        """

        execution_id = execution.id

        destination = canonical(execution.destination_path)

        # 1. Ensure the resulting observation (idempotent).
        result_observation_id = self._ensure_result_observation(
            execution,
            proposal,
            destination,
        )

        # 2. Ensure execution-authorised continuity (idempotent).
        continuity_id = self._ensure_continuity(
            execution,
            proposal,
            result_observation_id,
        )

        # 3. Drive to SUCCEEDED from wherever the durable state is.
        order = (
            STATE_VERIFYING,
            STATE_OBSERVATION_PERSISTENCE,
            STATE_PROVENANCE_PERSISTENCE,
            STATE_SUCCEEDED,
        )

        current = self.executions.get(execution_id)

        if current.state not in order:

            raise ValueError(
                f"organisation execution {execution_id} is "
                f"'{current.state}'; it cannot be finalised from "
                f"this state"
            )

        index = order.index(current.state)

        for target in order[index + 1:]:

            current = self.executions.update_state(
                execution_id,
                state=target,
                result_observation_id=result_observation_id,
                continuity_id=continuity_id,
                clear_error=(target == STATE_SUCCEEDED),
            )

        self._notify_execution(current)

        return current

    def _ensure_result_observation(
        self,
        execution,
        proposal,
        destination,
    ) -> int:
        """
        Return the resulting observation id, reusing an existing
        execution-authorised observation for this media at this
        destination when one already exists (idempotency across
        recovery boundaries).
        """

        if execution.result_observation_id is not None:

            return execution.result_observation_id

        existing = (
            self.media_repository
            .find_execution_authorised_observation(
                media_id=proposal.media_id,
                path=destination,
                execution_id=execution.id,
            )
        )

        if existing is not None:

            return existing

        observation_id = (
            self.media_repository
            .record_organisation_execution_observation(
                media_id=proposal.media_id,
                path=destination,
                source_observation_id=(
                    execution.source_observation_id
                ),
                execution_id=execution.id,
            )
        )

        self.media_repository.connection.commit()

        return observation_id

    def _ensure_continuity(
        self,
        execution,
        proposal,
        result_observation_id,
    ) -> int:
        """
        Return the continuity id, reusing an existing
        execution-authorised continuity record for this execution when
        one already exists (idempotency across recovery boundaries).
        """

        if execution.continuity_id is not None:

            return execution.continuity_id

        existing = self.executions.continuity_for(execution.id)

        if existing:

            return existing[0]["id"]

        continuity_id = self.executions.create_continuity(
            execution_id=execution.id,
            media_id=proposal.media_id,
            source_observation_id=(
                execution.source_observation_id
            ),
            result_observation_id=result_observation_id,
        )

        self.executions.connection.commit()

        return continuity_id

    # ---------------------------------------------------------
    # recovery / reconciliation
    # ---------------------------------------------------------

    def _reconcile(self, execution):
        """
        Inspect actual filesystem reality and classify the operation.
        Never guesses; never auto-reverses a move; only retries a move
        after fresh precondition validation.

        The execution may have been interrupted at any boundary after
        claiming its scope (EXECUTING / VERIFYING /
        OBSERVATION_PERSISTENCE / PROVENANCE_PERSISTENCE) or while
        already classified (INTERRUPTED / RECOVERY_REQUIRED /
        PRECONDITION_VERIFIED). Filesystem reality decides, never the
        persisted state alone.

        Cases:

        - source exists / destination absent  -> move not performed;
          retry permitted after fresh precondition validation
        - source absent / destination exists  -> move may have
          completed; verify destination against recorded source-state
          evidence, then finalise idempotently (no duplicate
          observation / continuity / provenance)
        - both exist  -> ambiguous; NAMOA does not guess
        - neither exists  -> unresolved; NAMOA does not guess
        - destination exists but mismatches  -> conflicting
        """

        proposal = self.organisation_records.get_proposal(
            execution.proposal_id
        )

        if proposal is None:

            self.executions.update_state(
                execution.id,
                state=STATE_FAILED,
                error=(
                    "proposal no longer exists; cannot reconcile"
                ),
            )

            self._notify_execution(self.executions.get(execution.id))

            return

        if execution.state in (
            STATE_PRECONDITION_VERIFIED,
            STATE_EXECUTING,
            STATE_VERIFYING,
            STATE_OBSERVATION_PERSISTENCE,
            STATE_PROVENANCE_PERSISTENCE,
            STATE_INTERRUPTED,
        ):

            # A raw, possibly-in-progress state is first classified
            # as uncertainty before filesystem reality decides.
            self.executions.update_state(
                execution.id,
                state=STATE_RECOVERY_REQUIRED,
                error=(
                    "interruption detected; reconciling against "
                    "actual filesystem reality"
                ),
            )

            self._notify_execution(
                self.executions.get(execution.id)
            )

            execution = self.executions.get(execution.id)

        source = canonical(execution.source_path)

        destination = canonical(execution.destination_path)

        source_present = os.path.lexists(source)

        destination_present = os.path.lexists(destination)

        if source_present and not destination_present:

            # Move did not happen. Allow a fresh, re-validated attempt.
            self.executions.update_state(
                execution.id,
                state=STATE_APPROVED,
                error=(
                    "reconciliation: source present, destination "
                    "absent; move had not occurred. A retry will "
                    "re-validate all preconditions before mutating."
                ),
            )

            return

        if not source_present and destination_present:

            # The move may have completed. Verify the destination
            # against the recorded expected source-state evidence
            # before completing.
            try:

                self._verify_postconditions(
                    execution, proposal, self._library_roots(proposal)
                )

            except OrganisationSafetyError as error:

                self.executions.update_state(
                    execution.id,
                    state=STATE_RECOVERY_REQUIRED,
                    error=(
                        "reconciliation: destination present but "
                        f"failed verification: {error}"
                    ),
                )

                self._notify_execution(
                    self.executions.get(execution.id)
                )

                return

            self.executions.update_state(
                execution.id,
                state=STATE_VERIFYING,
                error=(
                    "reconciliation: source absent and destination "
                    "verified; finalising the completed move"
                ),
            )

            self._finalise(execution, proposal)

            return

        if source_present and destination_present:

            self.executions.update_state(
                execution.id,
                state=STATE_RECOVERY_REQUIRED,
                error=(
                    "reconciliation: BOTH source and destination "
                    "exist; state is ambiguous. NAMOA does not guess; "
                    "manual investigation is required."
                ),
            )

            self._notify_execution(
                self.executions.get(execution.id)
            )

            return

        # neither present
        self.executions.update_state(
            execution.id,
            state=STATE_RECOVERY_REQUIRED,
            error=(
                "reconciliation: neither source nor destination "
                "exists; state is unresolved. NAMOA does not guess; "
                "manual investigation is required."
            ),
        )

        self._notify_execution(self.executions.get(execution.id))

    # ---------------------------------------------------------
    # concurrency guards
    # ---------------------------------------------------------

    def _assert_no_destination_lineage(
        self, media_id, destination
    ) -> None:

        destination_c = canonical(destination)

        for lineage in self.media_repository.get_active_lineages():

            if lineage.id == media_id:

                continue

            if canonical(lineage.file_path) == destination_c:

                raise OrganisationSafetyError(
                    f"destination {destination} is already owned by "
                    f"another media lineage {lineage.id}; refusing"
                )

    # ---------------------------------------------------------
    # internals
    # ---------------------------------------------------------

    def _get(self, execution_id):

        execution = self.executions.get(execution_id)

        if execution is None:

            raise ValueError(
                f"organisation execution {execution_id} not found"
            )

        return execution

    # ---------------------------------------------------------
    # Sprint 15: metadata staleness + provider review gates
    # ---------------------------------------------------------

    def _metadata_citations(self, proposal) -> list:
        citations = (proposal.evidence or {}).get(
            "metadata_citations", []
        )

        return list(citations or [])

    def _assert_metadata_current(self, proposal) -> None:
        """
        Refuse execution when cited provider metadata has
        been superseded by a re-fetch with changed
        decision inputs. Proposals without citations
        (legacy rows) skip this check.
        """

        for citation in self._metadata_citations(proposal):
            observation_id = citation.get("observation_id")

            if observation_id is None:
                continue

            current, reason = (
                self.organisation_records
                .metadata_observation_freshness(
                    int(observation_id)
                )
            )

            if not current:
                raise ValueError(
                    f"organisation proposal {proposal.id} "
                    f"is stale: {reason}"
                )

    # ---------------------------------------------------------
    # Sprint 15: scope-action execution
    # ---------------------------------------------------------

    #: Scope action types the execution authority can
    #: drive. File-grain types are refused here: they
    #: execute through per-file proposals, never as
    #: scope executions.
    EXECUTABLE_SCOPE_ACTIONS = frozenset(
        {
            SCOPE_ACTION_DIRECTORY_RENAME,
            SCOPE_ACTION_DIRECTORY_MOVE,
            SCOPE_ACTION_SUBTREE_RELOCATION,
            SCOPE_ACTION_DIRECTORY_CREATION,
        }
    )

    def execute_scope_action(
        self,
        scope_action_id,
        *,
        actor: str = "human",
    ):
        """
        Execute one approved scope action through the full
        safe sequence, reusing the per-file lifecycle
        vocabulary, safety module, scope-claim
        concurrency, verification, recovery, and
        provenance semantics. Returns the final scope
        execution record.

        Idempotency mirrors per-file execute(): an
        existing scope execution is reconciled first or
        refused when terminal.
        """

        from app.models.organisation import (
            SCOPE_ACTION_NO_MUTATION,
        )

        action = self._require_accepted_scope_action(
            scope_action_id
        )

        if action.action_type == SCOPE_ACTION_NO_MUTATION:
            raise ValueError(
                f"organisation scope action "
                f"{scope_action_id} requires no "
                f"filesystem mutation; nothing to execute"
            )

        if action.action_type not in (
            self.EXECUTABLE_SCOPE_ACTIONS
        ):
            raise ValueError(
                f"organisation scope action "
                f"{scope_action_id} has type "
                f"'{action.action_type}'; only structural "
                f"directory actions execute here "
                f"(file-grain actions execute through "
                f"their per-file proposals)"
            )

        self._assert_scope_metadata_current(action)

        execution = (
            self.organisation_records
            .get_scope_execution_by_action(scope_action_id)
        )

        if execution is not None:
            if execution.state == STATE_SUCCEEDED:
                raise ValueError(
                    f"organisation scope action "
                    f"{scope_action_id} has already been "
                    f"executed (scope execution "
                    f"{execution.id}); it will not run again"
                )

            if execution.state == STATE_FAILED:
                raise ValueError(
                    f"organisation scope action "
                    f"{scope_action_id} failed to execute "
                    f"(scope execution {execution.id}); "
                    f"re-approve or raise a new scope action"
                )

            if execution.state in RECOVERABLE_STATES:
                self._reconcile_scope(execution, action)
                execution = (
                    self.organisation_records
                    .get_scope_execution(execution.id)
                )

            if execution.state not in DRIVABLE_STATES:
                raise ValueError(
                    f"organisation scope action "
                    f"{scope_action_id} requires manual "
                    f"reconciliation (scope execution "
                    f"{execution.id}); it is "
                    f"'{execution.state}'"
                )

        if execution is None:
            execution_id = (
                self.organisation_records
                .create_scope_execution(
                    scope_action_id=action.id,
                    decision_run_id=action.decision_run_id,
                    action_type=action.action_type,
                    source_path=action.source_path,
                    destination_path=action.destination_path,
                    descendant_manifest=[
                        {
                            "media_id": item.get("media_id"),
                            "relative_path": item.get(
                                "relative_path"
                            ),
                            "size_bytes": item.get(
                                "size_bytes"
                            ),
                            "mtime_ns": item.get("mtime_ns"),
                            "source_observation_id": item.get(
                                "source_observation_id"
                            ),
                        }
                        for item in (
                            action.descendant_manifest or []
                        )
                    ],
                    actor=actor,
                )
            )

            self.organisation_records.connection.commit()

            execution = (
                self.organisation_records
                .get_scope_execution(execution_id)
            )

        return self._drive_scope(execution, action)

    def recover_scope_execution(
        self,
        scope_execution_id,
        *,
        actor: str = "system",
    ):
        """
        Reconcile a scope execution that may be interrupted
        anywhere after the scope claim by inspecting actual
        filesystem reality. Returns the updated record.
        """

        _ = actor

        execution = self._get_scope_execution(
            scope_execution_id
        )

        action = self.organisation_records.get_scope_action(
            execution.scope_action_id
        )

        if action is None:
            raise ValueError(
                f"organisation scope action for scope "
                f"execution {scope_execution_id} no "
                f"longer exists; cannot reconcile"
            )

        if execution.state not in RECOVERABLE_STATES:
            raise ValueError(
                f"organisation scope execution "
                f"{scope_execution_id} is "
                f"'{execution.state}'; nothing to recover"
            )

        self._reconcile_scope(execution, action)

        return self.organisation_records.get_scope_execution(
            scope_execution_id
        )

    def get_scope_execution(self, scope_execution_id):
        return self._get_scope_execution(scope_execution_id)

    def list_scope_executions(self, limit=100):
        return (
            self.organisation_records
            .list_scope_executions(limit=limit)
        )

    def scope_execution_events(self, scope_execution_id):
        self._get_scope_execution(scope_execution_id)

        return (
            self.organisation_records
            .scope_execution_events_for(scope_execution_id)
        )

    def scope_continuity(self, scope_execution_id):
        self._get_scope_execution(scope_execution_id)

        return (
            self.organisation_records.scope_continuity_for(
                scope_execution_id
            )
        )

    def _get_scope_execution(self, scope_execution_id):
        execution = (
            self.organisation_records.get_scope_execution(
                scope_execution_id
            )
        )

        if execution is None:
            raise ValueError(
                f"organisation scope execution "
                f"{scope_execution_id} not found"
            )

        return execution

    def _require_accepted_scope_action(self, scope_action_id):
        action = self.organisation_records.get_scope_action(
            scope_action_id
        )

        if action is None:
            raise ValueError(
                f"organisation scope action "
                f"{scope_action_id} not found"
            )

        if action.state != "accepted":
            raise ValueError(
                f"organisation scope action "
                f"{scope_action_id} is '{action.state}'; "
                f"only approved ('accepted') scope "
                f"actions may execute"
            )

        return action

    def _assert_scope_metadata_current(self, action) -> None:
        """
        Refuse scope execution when any covered
        descendant proposal cites superseded provider
        metadata. Mirrors the per-file staleness gate
        across the whole descendant set.
        """

        for proposal_id in (
            action.descendant_proposal_ids or []
        ):
            proposal = self.organisation_records.get_proposal(
                proposal_id
            )

            if proposal is None:
                raise ValueError(
                    f"organisation scope action "
                    f"{action.id} covers unknown proposal "
                    f"{proposal_id}; refusing scope "
                    f"execution"
                )

            self._assert_metadata_current(proposal)

    def _scope_library_roots(self, action) -> list:
        run = self.organisation_records.get_decision_run(
            action.decision_run_id
        )

        if run is None:
            raise ValueError(
                f"organisation decision run "
                f"{action.decision_run_id} not found"
            )

        return list(run.library_roots)

    def _drive_scope(self, execution, action):
        """
        Drive one scope execution through the shared
        lifecycle to SUCCEEDED or an honest
        failure/recovery state. Structural mutation
        happens only after EXECUTING is durably
        persisted with the scope claimed.
        """

        execution_id = execution.id

        if execution.state == STATE_PROPOSED:
            self.organisation_records.update_scope_execution_state(
                execution_id, state=STATE_APPROVED, error=None
            )

        try:
            self._verify_scope_preconditions(
                execution, action
            )
        except (OrganisationSafetyError, ValueError) as error:
            self._fail_scope(
                execution_id,
                f"{error}",
                action=action,
            )
            return self.organisation_records.get_scope_execution(
                execution_id
            )

        self.organisation_records.update_scope_execution_state(
            execution_id,
            state=STATE_PRECONDITION_VERIFIED,
        )

        try:
            self.organisation_records.claim_scope_execution(
                execution_id
            )
        except Exception as error:
            self._fail_scope(
                execution_id,
                f"{error}",
                action=action,
            )
            return self.organisation_records.get_scope_execution(
                execution_id
            )

        source = canonical(execution.source_path)
        destination = canonical(execution.destination_path)

        try:
            if action.action_type == (
                SCOPE_ACTION_DIRECTORY_CREATION
            ):
                ensure_destination_parent(destination)
                os.makedirs(destination, exist_ok=False)
            else:
                ensure_destination_parent(destination)
                os.rename(source, destination)
        except OSError as error:
            self._fail_scope(
                execution_id,
                f"structural move failed: {error}",
                action=action,
            )
            return self.organisation_records.get_scope_execution(
                execution_id
            )

        self.organisation_records.update_scope_execution_state(
            execution_id,
            state=STATE_VERIFYING,
        )

        try:
            self._verify_scope_postconditions(
                execution, action
            )
        except OrganisationSafetyError as error:
            self.organisation_records.update_scope_execution_state(
                execution_id,
                state=STATE_RECOVERY_REQUIRED,
                error=f"{error}",
            )
            self._notify_scope_execution(
                self.organisation_records.get_scope_execution(
                    execution_id
                ),
                action,
            )
            return self.organisation_records.get_scope_execution(
                execution_id
            )

        return self._finalise_scope(execution, action)

    def _fail_scope(
        self, execution_id, error, *, action=None
    ):
        self.organisation_records.update_scope_execution_state(
            execution_id,
            state=STATE_FAILED,
            error=error,
        )

        try:
            self.organisation_records.release_scope_paths(
                execution_id
            )
        except Exception:
            pass

        if action is not None:
            self._notify_scope_execution(
                self.organisation_records.get_scope_execution(
                    execution_id
                ),
                action,
            )

    def _verify_scope_preconditions(
        self, execution, action
    ) -> None:
        roots = self._scope_library_roots(action)

        source = execution.source_path
        destination = execution.destination_path

        if action.action_type == SCOPE_ACTION_DIRECTORY_CREATION:
            parent = os.path.dirname(canonical(destination))
            validate_directory_source(parent, roots)
            validate_directory_destination(
                destination, roots, must_be_absent=True
            )
        else:
            validate_directory_source(source, roots)
            validate_directory_destination(
                destination, roots, must_be_absent=True
            )

            if canonical(source) == canonical(destination):
                raise OrganisationSafetyError(
                    "scope source equals scope destination; "
                    "nothing to organise"
                )

            # A cross-device structural operation is never
            # a simple rename: refuse rather than disguise
            # copy/delete semantics.
            try:
                source_device = os.stat(source).st_dev
                parent = os.path.dirname(
                    canonical(destination)
                )
                parent_device = os.stat(parent).st_dev
            except OSError as error:
                raise OrganisationSafetyError(
                    f"cannot establish scope filesystems: "
                    f"{error}"
                ) from error

            if source_device != parent_device:
                raise OrganisationSafetyError(
                    "scope source and destination live on "
                    "different filesystems; refusing to "
                    "disguise a copy/delete as a rename"
                )

        # Every covered descendant must still be the
        # authorised observation context.
        for item in execution.descendant_manifest or []:
            self._verify_scope_descendant(item, action)

        # Provider-managed overlap recheck: overlap that
        # appeared after planning (not among the
        # reviewed conditions) refuses execution.
        self._recheck_provider_overlap(execution, action)

        # Destination must not be owned by another lineage
        # and no conflicting scope claim may exist; the
        # claim itself is taken by claim_scope_execution.
        self._assert_no_destination_lineage_scope(
            execution, action
        )

    def _verify_scope_descendant(self, item, action) -> None:
        media_id = item.get("media_id")
        relative = item.get("relative_path")
        source = action.source_path

        lineage = self.media_repository.get_media_item(
            media_id
        )

        if lineage is None or lineage.status != "active":
            raise OrganisationSafetyError(
                f"descendant media {media_id} is "
                f"not active; the scope source is no "
                f"longer the authorised context"
            )

        expected = os.path.join(source, relative or "")

        if canonical(lineage.file_path) != canonical(
            expected
        ):
            raise OrganisationSafetyError(
                f"descendant media {media_id} no longer "
                f"resides at the planned scope path "
                f"{expected}; re-plan"
            )

        observation_id = item.get("source_observation_id")

        if observation_id is None:
            raise OrganisationSafetyError(
                f"descendant media {media_id} cites no "
                f"source observation; refusing scope "
                f"execution"
            )

        observation = self.media_repository.get_observation_by_id(
            int(observation_id)
        )

        if observation is None:
            raise OrganisationSafetyError(
                f"descendant media {media_id} cites source "
                f"observation {observation_id} which no "
                f"longer exists"
            )

        try:
            stat = os.stat(expected)
        except OSError as error:
            raise OrganisationSafetyError(
                f"descendant media {media_id} source file "
                f"is not accessible: {error}"
            ) from error

        if (
            stat.st_size != observation.size_bytes
            or stat.st_mtime_ns != observation.file_mtime_ns
        ):
            raise OrganisationSafetyError(
                f"descendant media {media_id} changed "
                f"since the authorised scope plan; "
                f"re-plan"
            )

    def _scope_provider_paths(self, action) -> set:
        """
        Provider-known paths relevant to a scope action,
        gathered from the latest metadata observations of
        its descendants. Read-only.
        """

        known = set()

        for proposal_id in (
            action.descendant_proposal_ids or []
        ):
            proposal = self.organisation_records.get_proposal(
                proposal_id
            )

            if proposal is None:
                continue

            media_id = proposal.media_id

            try:
                records = (
                    self.organisation_records
                    .list_metadata_observations(media_id)
                )
            except Exception:
                continue

            for record in records:
                payload = record.payload or {}

                for key in (
                    "root_folder_path",
                    "provider_path",
                    "series_path",
                ):
                    value = payload.get(key)

                    if value:
                        try:
                            known.add(canonical(value))
                        except (OSError, ValueError):
                            continue

        return known

    def _recheck_provider_overlap(
        self, execution, action
    ) -> None:
        reviewed = any(
            isinstance(condition, dict)
            and condition.get("kind")
            == "provider-managed-path"
            for condition in (action.review_conditions or [])
        )

        provider_paths = self._scope_provider_paths(action)

        if not provider_paths:
            return

        overlap = self._paths_overlap_provider(
            execution.source_path,
            execution.destination_path,
            provider_paths,
        )

        if overlap and not reviewed:
            raise OrganisationSafetyError(
                "scope overlaps a provider-managed path "
                "that was not among the reviewed scope "
                "conditions; re-plan with explicit review"
            )

    def _paths_overlap_provider(
        self, source: str, destination: str, known: set
    ) -> bool:
        try:
            sides = [canonical(source), canonical(destination)]
        except (OSError, ValueError):
            return True

        for side in sides:
            for path in known:
                if (
                    side == path
                    or side.startswith(path + os.sep)
                    or path.startswith(side + os.sep)
                ):
                    return True

        return False

    def _assert_no_destination_lineage_scope(
        self, execution, action
    ) -> None:
        _ = action

        try:
            lineages = (
                self.media_repository.get_active_lineages()
            )
        except Exception:
            return

        try:
            destination = canonical(
                execution.destination_path
            )
        except (OSError, ValueError):
            return

        for lineage in lineages:
            try:
                current = canonical(
                    lineage.file_path or ""
                )
            except (OSError, ValueError):
                continue

            if current == destination or current.startswith(
                destination + os.sep
            ):
                raise OrganisationSafetyError(
                    f"destination {destination} overlaps "
                    f"media lineage {lineage.id}; refusing"
                )

    def _verify_scope_postconditions(
        self, execution, action
    ) -> None:
        from app.execution.organisation_safety import (
            subtree_file_manifest,
        )

        source = execution.source_path
        destination = execution.destination_path

        if action.action_type == SCOPE_ACTION_DIRECTORY_CREATION:
            if not os.path.isdir(destination):
                raise OrganisationSafetyError(
                    "postcondition failed: created directory "
                    f"does not exist: {destination}"
                )
            if os.path.islink(destination):
                raise OrganisationSafetyError(
                    "postcondition failed: created path is "
                    f"a symlink: {destination}"
                )
            return

        if not os.path.isdir(destination):
            raise OrganisationSafetyError(
                "postcondition failed: expected directory "
                f"destination does not exist: {destination}"
            )

        if os.path.lexists(source):
            raise OrganisationSafetyError(
                "postcondition failed: scope source is "
                f"still present: {source}"
            )

        if os.path.islink(destination):
            raise OrganisationSafetyError(
                "postcondition failed: destination is a "
                f"symlink: {destination}"
            )

        live = subtree_file_manifest(destination)

        expected = {}

        for item in execution.descendant_manifest or []:
            relative = item.get("relative_path")

            if not relative:
                continue

            expected[relative] = (
                item.get("size_bytes"),
                item.get("mtime_ns"),
            )

        live_files = {
            key
            for key, value in live.items()
            if isinstance(value, tuple) and len(value) == 2
        }

        if set(expected) != live_files:
            missing = sorted(set(expected) - live_files)
            extra = sorted(live_files - set(expected))
            raise OrganisationSafetyError(
                "postcondition failed: destination tree "
                "does not match the planned manifest "
                f"(missing={missing[:5]}, "
                f"extra={extra[:5]})"
            )

        for relative, (size, mtime) in expected.items():
            if live.get(relative) != (size, mtime):
                raise OrganisationSafetyError(
                    "postcondition failed: descendant "
                    f"'{relative}' size/mtime drifted "
                    f"during scope execution"
                )

        non_files = sorted(
            key
            for key, value in live.items()
            if not (
                isinstance(value, tuple) and len(value) == 2
            )
        )

        if non_files:
            raise OrganisationSafetyError(
                "postcondition failed: non-regular tree "
                f"members appeared: {non_files[:5]}"
            )

    def _finalise_scope(self, execution, action):
        """
        Idempotent scope finalisation: one new observation
        plus one continuity row per affected descendant
        through the existing record functions, then walk
        to SUCCEEDED. Descendant progress is committed
        incrementally so recovery never duplicates rows.
        """

        _ = action

        execution_id = execution.id
        destination = canonical(execution.destination_path)

        completed = list(
            execution.descendants_completed or []
        )

        for item in execution.descendant_manifest or []:
            media_id = item.get("media_id")
            relative = item.get("relative_path") or ""

            if media_id in completed:
                continue

            new_path = os.path.join(destination, relative)

            existing = (
                self.media_repository
                .find_execution_authorised_observation(
                    media_id=media_id,
                    path=new_path,
                    execution_id=execution_id,
                    identity_method=(
                        "organisation_scope_execution_continuity"
                    ),
                )
            )

            if existing is not None:
                result_observation_id = existing
            else:
                result_observation_id = (
                    self.media_repository
                    .record_organisation_execution_observation(
                        media_id=media_id,
                        path=new_path,
                        source_observation_id=item.get(
                            "source_observation_id"
                        ),
                        execution_id=execution_id,
                        identity_method=(
                            "organisation_scope_execution_continuity"
                        ),
                        authority=(
                            "organisation_scope_execution"
                        ),
                    )
                )

                self.media_repository.connection.commit()

            already = {
                row["media_id"]
                for row in (
                    self.organisation_records
                    .scope_continuity_for(execution_id)
                )
            }

            if media_id not in already:
                self.organisation_records.create_scope_continuity(
                    scope_execution_id=execution_id,
                    media_id=media_id,
                    source_observation_id=item.get(
                        "source_observation_id"
                    ),
                    result_observation_id=(
                        result_observation_id
                    ),
                )

                self.organisation_records.connection.commit()

            completed.append(media_id)

            self.organisation_records.update_scope_execution_state(
                execution_id,
                state="observation_persistence",
                descendants_completed=list(completed),
            )

        current = self.organisation_records.get_scope_execution(
            execution_id
        )

        order = (
            STATE_VERIFYING,
            STATE_OBSERVATION_PERSISTENCE,
            STATE_PROVENANCE_PERSISTENCE,
            STATE_SUCCEEDED,
        )

        if current.state not in order:
            raise ValueError(
                f"organisation scope execution "
                f"{execution_id} is '{current.state}'; it "
                f"cannot be finalised from this state"
            )

        index = order.index(current.state)

        for target in order[index + 1:]:
            current = self.organisation_records.update_scope_execution_state(
                execution_id,
                state=target,
                clear_error=(target == STATE_SUCCEEDED),
            )

        try:
            self.organisation_records.release_scope_paths(
                execution_id
            )
        except Exception:
            pass

        self._notify_scope_execution(current, action)

        return current

    def _reconcile_scope(self, execution, action):
        """
        Reality-based scope reconciliation. Never guesses;
        never auto-reverses; only retries after fresh
        precondition validation.
        """

        if execution.state in (
            STATE_PRECONDITION_VERIFIED,
            STATE_EXECUTING,
            STATE_VERIFYING,
            STATE_OBSERVATION_PERSISTENCE,
            STATE_PROVENANCE_PERSISTENCE,
            STATE_INTERRUPTED,
        ):
            self.organisation_records.update_scope_execution_state(
                execution.id,
                state=STATE_RECOVERY_REQUIRED,
                error=(
                    "interruption detected; reconciling "
                    "scope against actual filesystem reality"
                ),
            )

            self._notify_scope_execution(
                self.organisation_records.get_scope_execution(
                    execution.id
                ),
                action,
            )

            execution = (
                self.organisation_records
                .get_scope_execution(execution.id)
            )

        source = canonical(execution.source_path)
        destination = canonical(execution.destination_path)

        try:
            source_present = os.path.lexists(source)
            destination_present = os.path.lexists(destination)
        except (OSError, ValueError):
            source_present = True
            destination_present = True

        if source_present and not destination_present:
            self.organisation_records.update_scope_execution_state(
                execution.id,
                state=STATE_APPROVED,
                error=(
                    "reconciliation: scope source present, "
                    "destination absent; structural move "
                    "had not occurred. A retry will "
                    "re-validate all preconditions."
                ),
            )
            return

        if not source_present and destination_present:
            try:
                self._verify_scope_postconditions(
                    execution, action
                )
            except OrganisationSafetyError as error:
                self.organisation_records.update_scope_execution_state(
                    execution.id,
                    state=STATE_RECOVERY_REQUIRED,
                    error=(
                        "reconciliation: destination "
                        "present but failed verification: "
                        f"{error}"
                    ),
                )
                self._notify_scope_execution(
                    self.organisation_records.get_scope_execution(
                        execution.id
                    ),
                    action,
                )
                return

            self.organisation_records.update_scope_execution_state(
                execution.id,
                state=STATE_VERIFYING,
                error=(
                    "reconciliation: scope source absent "
                    "and destination verified; finalising "
                    "the completed structural move"
                ),
            )
            self._finalise_scope(execution, action)
            return

        self.organisation_records.update_scope_execution_state(
            execution.id,
            state=STATE_RECOVERY_REQUIRED,
            error=(
                "reconciliation: scope source and "
                "destination state is ambiguous or "
                "unresolved; manual investigation "
                "required"
            ),
        )

        self._notify_scope_execution(
            self.organisation_records.get_scope_execution(
                execution.id
            ),
            action,
        )

    def _notify_scope_execution(
        self, execution, action=None
    ):
        _ = action

        if execution.state == STATE_SUCCEEDED:
            descendants = len(
                execution.descendant_manifest or []
            )
            self._notify(
                "success",
                "Organisation scope change complete",
                f"{execution.source_path} -> "
                f"{execution.destination_path} · "
                f"{descendants} descendants verified "
                f"and recorded",
            )
        elif execution.state == STATE_FAILED:
            self._notify(
                "error",
                "Organisation scope change failed",
                f"{execution.source_path} · "
                f"{execution.error or 'execution failed'}",
            )
        elif execution.state in (
            STATE_RECOVERY_REQUIRED,
            STATE_INTERRUPTED,
        ):
            self._notify(
                "attention",
                "Organisation scope change needs recovery",
                f"{execution.source_path} · "
                f"{execution.error or 'filesystem state is uncertain'}",
            )
