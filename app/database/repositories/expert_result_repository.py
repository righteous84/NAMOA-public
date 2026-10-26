import json

from app.models.expert_result import ExpertResult
from app.models.expert_reasoning import (
    AgreementState,
    AlternativeInterpretation,
    DomainAnalysis,
    EvidenceReference,
    EvidenceRole,
    ExpertData,
)


def _deserialize_evidence_reference(
    payload: dict,
) -> EvidenceReference:
    """
    Reconstruct an immutable EvidenceReference.
    """

    return EvidenceReference(
        source=payload["source"],
        raw_confidence=payload["raw_confidence"],
        weighted_confidence=payload["weighted_confidence"],
        role=EvidenceRole(
            payload["role"]
        ),
        evidence_id=payload.get(
            "evidence_id"
        ),
        matched_text=payload.get(
            "matched_text"
        ),
    )


def _deserialize_expert_data(
    payload: dict,
) -> ExpertData:
    """
    Reconstruct ExpertData from its immutable
    JSON provenance snapshot.
    """

    domains = {}

    for domain_name, domain_payload in (
        payload.get("domains", {})
    ).items():

        selected_references = tuple(
            _deserialize_evidence_reference(item)
            for item in domain_payload.get(
                "selected_references",
                [],
            )
        )

        rejected_references = tuple(
            _deserialize_evidence_reference(item)
            for item in domain_payload.get(
                "rejected_references",
                [],
            )
        )

        alternatives = tuple(
            AlternativeInterpretation(
                value=item["value"],
                confidence=item["confidence"],
                support_count=item["support_count"],
            )
            for item in domain_payload.get(
                "alternatives",
                [],
            )
        )

        domains[domain_name] = DomainAnalysis(
            selected_value=domain_payload[
                "selected_value"
            ],
            confidence=domain_payload[
                "confidence"
            ],
            agreement=AgreementState(
                domain_payload["agreement"]
            ),
            has_conflict=domain_payload[
                "has_conflict"
            ],
            uncertainty=domain_payload[
                "uncertainty"
            ],
            selected_references=selected_references,
            rejected_references=rejected_references,
            alternatives=alternatives,
        )

    return ExpertData(
        domains=domains
    )


class ExpertResultRepository:
    """
    Persistence boundary for ExpertResult provenance.

    Stores immutable ExpertResult snapshots produced
    by Experts.

    This repository does not:

        - execute experts
        - interpret evidence
        - make decisions
        - modify ExpertResults
    """

    def __init__(
        self,
        connection,
    ):
        self.connection = connection

    def save(
        self,
        analysis_run_id: int,
        expert_results: list[ExpertResult],
    ) -> None:
        """
        Persist immutable ExpertResult snapshots.

        Expert-level knowledge provenance is stored directly
        on the ExpertResult snapshot.

        Run-level knowledge provenance remains in
        analysis_run_knowledge.
        """

        if not expert_results:
            return

        snapshots = [
            result.to_snapshot()
            for result in expert_results
        ]

        self.connection.executemany(
            """
            INSERT INTO expert_results (
                analysis_run_id,
                expert_name,
                confidence,
                observations_json,
                notes,
                expert_data_json,
                knowledge_set_ids_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    analysis_run_id,
                    snapshot["expert_name"],
                    snapshot["confidence"],
                    snapshot["observations_json"],
                    snapshot["notes"],
                    snapshot["expert_data_json"],
                    snapshot["knowledge_set_ids_json"],
                )
                for snapshot in snapshots
            ],
        )

    def get_by_analysis_run(
        self,
        analysis_run_id: int,
    ) -> list[ExpertResult]:
        """
        Retrieve immutable ExpertResult snapshots.

        Persisted structured reasoning and per-Expert
        knowledge provenance are reconstructed from
        the stored snapshots.
        """

        rows = self.connection.execute(
            """
            SELECT
                expert_name,
                confidence,
                observations_json,
                notes,
                expert_data_json,
                knowledge_set_ids_json
            FROM expert_results
            WHERE analysis_run_id = ?
            ORDER BY id
            """,
            (
                analysis_run_id,
            ),
        ).fetchall()

        results = []

        for row in rows:

            expert_data = _deserialize_expert_data(
                json.loads(
                    row["expert_data_json"]
                )
            )

            knowledge_set_ids = set(
                json.loads(
                    row["knowledge_set_ids_json"]
                )
            )

            results.append(
                ExpertResult(
                    expert_name=row["expert_name"],
                    confidence=row["confidence"],
                    observations=json.loads(
                        row["observations_json"]
                    ),
                    notes=row["notes"],
                    expert_data=expert_data,
                    knowledge_set_ids=knowledge_set_ids,
                )
            )

        return results