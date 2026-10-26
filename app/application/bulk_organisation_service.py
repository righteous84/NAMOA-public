"""
Bulk organisation coordination (Sprint 15).

Thin orchestration over the organisation boundaries,
mirroring the Phase 12 bulk pattern without reusing
the optimisation bulk service across domains. Every
per-file and per-scope decision stays with its owning
boundary; this coordinator only sequences calls and
assembles honest verdicts.

- plan_many: pure planning per scope, no writes
- accept_many: existing per-item accept results for
  proposals and scope actions
- execute_many: serial execution, later actions
  proceed after any single failure
- describe_many: per-item outcome rows plus an
  honest bulk verdict

Serial execution only. No worker system, no threads,
no blanket approval. Recovery stays per execution
via the existing recover paths.
"""

from app.models.organisation_execution import (
    STATE_SUCCEEDED,
)


class BulkOrganisationService:
    """
    Application boundary for library-wide organisation
    reconciliation coordination.
    """

    def __init__(
        self,
        *,
        organisation_service,
        organisation_execution_service,
    ):
        self.organisation_service = organisation_service
        self.organisation_execution_service = (
            organisation_execution_service
        )

    # ---------------------------------------------------------
    # planning (pure, no writes)
    # ---------------------------------------------------------

    def plan_many(
        self,
        scopes,
        *,
        profile=None,
        preferences=None,
        metadata_scope="cached",
    ) -> dict:
        """
        Plan several scopes without persisting anything.
        Returns per-scope plans plus any planning
        refusals. One scope failing never prevents the
        others.
        """

        planned = []
        refused = []

        for scope in scopes or []:
            try:
                plan = self.organisation_service.plan_scope(
                    scope,
                    profile=profile,
                    preferences=preferences,
                    metadata_scope=metadata_scope,
                )
            except Exception as error:
                refused.append(
                    {
                        "scope": scope,
                        "reason": (
                    f"{type(error).__name__}: {error}"
                        ),
                    }
                )
                continue

            planned.append(
                {"scope": scope, "plan": plan}
            )

        return {"planned": planned, "refused": refused}

    # ---------------------------------------------------------
    # acceptance (per-item results)
    # ---------------------------------------------------------

    def accept_many(
        self,
        *,
        proposal_ids=None,
        scope_action_ids=None,
        accepted_by: str = "human",
    ) -> dict:
        """
        Accept proposals and scope actions with per-item
        results. Scope actions are accepted first: their
        covered descendant proposals transition with
        them atomically and are reported as deferred to
        scope rather than double-processed. A refusal
        for one item never prevents or silently approves
        another.
        """

        accepted_proposals = []
        refused_proposals = []
        deferred_to_scope = []

        covered = set()

        for action_id in scope_action_ids or []:
            try:
                action = (
                    self.organisation_service
                    .get_scope_action(int(action_id))
                )
            except Exception:
                continue

            covered.update(
                action["action"].descendant_proposal_ids
                or []
            )

        wanted = []

        for proposal_id in proposal_ids or []:
            try:
                clean = int(proposal_id)
            except (TypeError, ValueError):
                refused_proposals.append(
                    {
                        "proposal_id": proposal_id,
                        "reason": "invalid proposal id",
                    }
                )
                continue

            if clean in covered:
                deferred_to_scope.append(clean)
                continue

            wanted.append(clean)

        if wanted:
            result = self.organisation_service.accept_selected(
                wanted,
                accepted_by=accepted_by,
            )

            for entry in result.get("accepted", []):
                accepted_proposals.append(
                    {
                        "proposal_id": entry["proposal_id"],
                        "media_id": entry["media_id"],
                        "intent": entry["intent"],
                    }
                )

            for entry in result.get("refused", []):
                refused_proposals.append(
                    {
                        "proposal_id": entry["proposal_id"],
                        "reason": entry["reason"],
                    }
                )

        accepted_scopes = []
        refused_scopes = []

        for action_id in scope_action_ids or []:
            try:
                view = (
                    self.organisation_service
                    .accept_scope_action(
                        int(action_id),
                        accepted_by=accepted_by,
                    )
                )
            except Exception as error:
                refused_scopes.append(
                    {
                        "scope_action_id": action_id,
                        "reason": str(error),
                    }
                )
                continue

            accepted_scopes.append(view)

        return {
            "accepted_proposals": accepted_proposals,
            "refused_proposals": refused_proposals,
            "deferred_to_scope": deferred_to_scope,
            "accepted_scope_actions": accepted_scopes,
            "refused_scope_actions": refused_scopes,
        }

    # ---------------------------------------------------------
    # execution (serial, per-item results)
    # ---------------------------------------------------------

    def execute_many(
        self,
        *,
        proposal_ids=None,
        scope_action_ids=None,
        actor: str = "human",
    ) -> dict:
        """
        Execute accepted proposals and scope actions
        serially, one at a time, in the order given.
        A terminal failure never marks another item
        successful and never prevents later items.
        """

        succeeded = []
        failed = []

        for proposal_id in proposal_ids or []:
            try:
                record = (
                    self.organisation_execution_service
                    .execute(int(proposal_id), actor=actor)
                )
            except Exception as error:
                failed.append(
                    {
                        "kind": "proposal",
                        "proposal_id": proposal_id,
                        "state": None,
                        "reason": (
                            f"{type(error).__name__}: "
                            f"{error}"
                        ),
                    }
                )
                continue

            if record.state == STATE_SUCCEEDED:
                succeeded.append(
                    {
                        "kind": "proposal",
                        "proposal_id": proposal_id,
                        "execution_id": record.id,
                    }
                )
            else:
                failed.append(
                    {
                        "kind": "proposal",
                        "proposal_id": proposal_id,
                        "execution_id": record.id,
                        "state": record.state,
                        "reason": record.error,
                    }
                )

        for action_id in scope_action_ids or []:
            try:
                record = (
                    self.organisation_execution_service
                    .execute_scope_action(
                        int(action_id), actor=actor
                    )
                )
            except Exception as error:
                failed.append(
                    {
                        "kind": "scope_action",
                        "scope_action_id": action_id,
                        "state": None,
                        "reason": (
                            f"{type(error).__name__}: "
                            f"{error}"
                        ),
                    }
                )
                continue

            if record.state == STATE_SUCCEEDED:
                succeeded.append(
                    {
                        "kind": "scope_action",
                        "scope_action_id": action_id,
                        "scope_execution_id": record.id,
                    }
                )
            else:
                failed.append(
                    {
                        "kind": "scope_action",
                        "scope_action_id": action_id,
                        "scope_execution_id": record.id,
                        "state": record.state,
                        "reason": record.error,
                    }
                )

        return {
            "succeeded": succeeded,
            "failed": failed,
        }

    # ---------------------------------------------------------
    # honest bulk verdicts
    # ---------------------------------------------------------

    def describe_many(
        self,
        *,
        proposal_ids=None,
        scope_action_ids=None,
    ) -> dict:
        """
        Per-item outcome rows plus an honest bulk verdict.
        "succeeded" only when every resolved item
        succeeded; anything else is "incomplete". Bulk
        completion is never presented as proof that
        every item succeeded.
        """

        items = []

        covered_by_scope = set()

        for action_id in scope_action_ids or []:
            try:
                action = (
                    self.organisation_service
                    .get_scope_action(int(action_id))
                )
            except Exception:
                continue

            record = action["action"]

            execution = (
                self.organisation_execution_service
                .organisation_records
                .get_scope_execution_by_action(record.id)
            )

            if (
                execution is not None
                and execution.state == STATE_SUCCEEDED
            ):
                covered_by_scope.update(
                    record.descendant_proposal_ids or []
                )

        for proposal_id in proposal_ids or []:
            record = None

            if str(proposal_id).strip().lstrip(
                "-"
            ).isdigit():
                record = (
                    self.organisation_execution_service
                    .organisation_records.get_proposal(
                        int(proposal_id)
                    )
                )

            if record is None:
                items.append(
                    {
                        "kind": "proposal",
                        "proposal_id": proposal_id,
                        "resolved": False,
                        "reason": "proposal not found",
                    }
                )
                continue

            execution = (
                self.organisation_execution_service
                .get_by_proposal(record.id)
            )

            items.append(
                {
                    "kind": "proposal",
                    "proposal_id": record.id,
                    "media_id": record.media_id,
                    "intent": record.intent,
                    "resolved": True,
                    "proposal_state": record.state,
                    "succeeded": (
                        (
                            execution is not None
                            and execution.state
                            == STATE_SUCCEEDED
                        )
                        or record.id in covered_by_scope
                    ),
                    "via_scope_action": (
                        record.id in covered_by_scope
                    ),
                    "execution_state": (
                        execution.state
                        if execution is not None
                        else None
                    ),
                    "result_observation_id": (
                        execution.result_observation_id
                        if execution is not None
                        else None
                    ),
                    "error": (
                        execution.error
                        if execution is not None
                        else None
                    ),
                }
            )

        for action_id in scope_action_ids or []:
            try:
                action = (
                    self.organisation_service
                    .get_scope_action(int(action_id))
                )
            except Exception:
                items.append(
                    {
                        "kind": "scope_action",
                        "scope_action_id": action_id,
                        "resolved": False,
                        "reason": "scope action not found",
                    }
                )
                continue

            record = action["action"]

            descendant_media_ids = []

            for proposal_id in (
                record.descendant_proposal_ids or []
            ):
                proposal = (
                    self.organisation_execution_service
                    .organisation_records.get_proposal(
                        proposal_id
                    )
                )

                if proposal is not None:
                    descendant_media_ids.append(
                        proposal.media_id
                    )

            execution = (
                self.organisation_execution_service
                .organisation_records
                .get_scope_execution_by_action(record.id)
            )

            items.append(
                {
                    "kind": "scope_action",
                    "scope_action_id": record.id,
                    "action_type": record.action_type,
                    "resolved": True,
                    "scope_state": record.state,
                    "succeeded": (
                        execution is not None
                        and execution.state
                        == STATE_SUCCEEDED
                    ),
                    "execution_state": (
                        execution.state
                        if execution is not None
                        else None
                    ),
                    "descendant_media_ids": (
                        descendant_media_ids
                    ),
                    "error": (
                        execution.error
                        if execution is not None
                        else None
                    ),
                }
            )

        resolved = [
            item for item in items if item.get("resolved")
        ]

        verdict = (
            "succeeded"
            if items
            and len(resolved) == len(items)
            and all(item.get("succeeded") for item in items)
            else "incomplete"
        )

        return {
            "verdict": verdict,
            "succeeded_count": sum(
                1 for item in items if item.get("succeeded")
            ),
            "total_count": len(items),
            "items": items,
        }
