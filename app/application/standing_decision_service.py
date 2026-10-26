class StandingDecisionService:
    """
    Application boundary for durable standing user decisions.

    Persistence mechanics remain owned by
    StandingDecisionRepository.

    Standing-decision semantics remain deliberately narrow:
    a refusal suppresses re-presentation of a specific proposition for
    a specific media lineage; a revocation restores presentation.

    This service never changes analysis, validity, scoring, approval,
    or execution state.

    Transaction ownership remains with this application boundary.
    """

    def __init__(
        self,
        *,
        standing_decision_repository,
    ):
        self.standing_decision_repository = (
            standing_decision_repository
        )

    def get_decision(
        self,
        media_id: int,
        proposition: str,
    ):
        return self.standing_decision_repository.get(
            media_id,
            proposition,
        )

    def get_refused_propositions(
        self,
        media_id: int,
    ):
        return (
            self.standing_decision_repository
            .get_refused_propositions(media_id)
        )

    def get_history(
        self,
        media_id: int,
    ):
        return (
            self.standing_decision_repository
            .list_for_media(media_id)
        )

    def get_event_history(
        self,
        media_id: int,
        proposition: str,
    ):
        return (
            self.standing_decision_repository
            .events_for(
                media_id,
                proposition,
            )
        )

    def refuse(
        self,
        media_id: int,
        proposition: str,
        *,
        actor: str,
        reason: str | None = None,
    ):
        decision = self.standing_decision_repository.refuse(
            media_id,
            proposition,
            actor=actor,
            reason=reason,
        )

        self.standing_decision_repository.connection.commit()

        return decision

    def revoke(
        self,
        media_id: int,
        proposition: str,
        *,
        actor: str,
        reason: str | None = None,
    ):
        decision = self.standing_decision_repository.revoke(
            media_id,
            proposition,
            actor=actor,
            reason=reason,
        )

        self.standing_decision_repository.connection.commit()

        return decision

    def refuse_propositions(
        self,
        media_id: int,
        propositions,
        *,
        actor: str,
        reason: str | None = None,
    ):
        """
        Refuse several propositions for one media lineage as one
        atomic unit: either every refusal record (plus its history
        event) is persisted or none is. A single commit follows the
        existing transaction-ownership pattern of refuse(); any
        failure rolls the whole unit back and propagates, so the
        caller can report the candidate as not rejected. Refusal
        matching semantics are unchanged: each proposition is
        recorded through the same repository path as refuse().
        """

        repository = self.standing_decision_repository

        decisions = []

        try:
            for proposition in propositions or ():
                decisions.append(
                    repository.refuse(
                        media_id,
                        proposition,
                        actor=actor,
                        reason=reason,
                    )
                )

            repository.connection.commit()
        except Exception:
            repository.connection.rollback()
            raise

        return decisions