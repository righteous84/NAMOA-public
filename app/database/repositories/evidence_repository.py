from app.models.evidence_collection import EvidenceCollection
from app.models.classification_evidence import ClassificationEvidence

class EvidenceRepository:
    """
    Persistence boundary for classification evidence.

    Stores observations produced during analysis.

    This repository does not:
    - classify
    - interpret
    - score
    - make decisions
    """

    def __init__(self, connection):
        self.connection = connection


    def save(
        self,
        analysis_run_id: int,
        evidence_collection: EvidenceCollection,
    ) -> None:

        if not evidence_collection.all():
            return


        self.connection.executemany(
            """
            INSERT INTO classification_evidence (
                analysis_run_id,
                domain,
                value,
                confidence,
                source,
                evidence_id,
                matched_text
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    analysis_run_id,
                    evidence.domain,
                    evidence.value,
                    evidence.confidence,
                    evidence.source,
                    evidence.evidence_id,
                    evidence.matched_text,
                )
                for evidence
                in evidence_collection.all()
            ],
        )

    def get_by_analysis_run(
        self,
        analysis_run_id: int,
    ):
        """
        Retrieve immutable classification evidence.
        """

        from app.models.classification_evidence import (
            ClassificationEvidence
        )

        rows = self.connection.execute(
            """
            SELECT
                domain,
                value,
                confidence,
                source,
                evidence_id,
                matched_text
            FROM classification_evidence
            WHERE analysis_run_id = ?
            ORDER BY id
            """,
            (
                analysis_run_id,
            ),
        ).fetchall()


        return [
            ClassificationEvidence(
                domain=row["domain"],
                value=row["value"],
                confidence=row["confidence"],
                source=row["source"],
                evidence_id=row["evidence_id"],
                matched_text=row["matched_text"],
            )
            for row in rows
        ]