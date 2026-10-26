import json

from app.decision_engine.signals.decision_signal import DecisionSignal


class DecisionSignalRepository:
    """
    Persistence boundary for DecisionSignal provenance.

    Stores immutable snapshots produced by Decision Rules.

    This repository does not:
    - execute decision rules
    - calculate scores
    - modify DecisionSignals
    - perform fusion
    """

    def __init__(self, connection):
        self.connection = connection


    def save(
        self,
        analysis_run_id: int,
        signals: list[DecisionSignal],
    ) -> None:
        """
        Persist DecisionSignal snapshots for an analysis run.
        """

        if not signals:
            return

        self.connection.executemany(
            """
            INSERT INTO decision_signals (
                analysis_run_id,
                rule_name,
                signal_type,
                opportunity_score,
                confidence,
                reasoning_json,
                signal_data_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    analysis_run_id,
                    signal.rule,
                    signal.direction,
                    signal.opportunity_score,
                    signal.confidence,
                    json.dumps(
                        {
                            "notes": signal.notes,
                            "evidence": signal.evidence,
                            "proposition": signal.proposition,
                            "current_state": signal.current_state,
                            "target_state": signal.target_state,
                            "benefit": signal.benefit,
                            "cost": signal.cost,
                            "risk": signal.risk,
                            "reason": signal.reason,
                        }
                    ),
                    json.dumps(
                        signal.provenance
                    ),
                )
                for signal in signals
            ],
        )


    def get_by_analysis_run(
        self,
        analysis_run_id: int,
    ):

        import json

        from app.decision_engine.signals.decision_signal import (
            DecisionSignal
        )


        rows = self.connection.execute(
            """
            SELECT
                rule_name,
                signal_type,
                opportunity_score,
                confidence,
                reasoning_json,
                signal_data_json
            FROM decision_signals
            WHERE analysis_run_id = ?
            ORDER BY id
            """,
            (
                analysis_run_id,
            ),
        ).fetchall()


        signals = []


        for row in rows:

            reasoning = json.loads(
                row["reasoning_json"]
            )

            signals.append(
                DecisionSignal(
                    rule=row["rule_name"],
                    direction=row["signal_type"],
                    opportunity_score=row["opportunity_score"],
                    confidence=row["confidence"],
                    notes=reasoning.get("notes", ""),
                    evidence=reasoning.get("evidence", {}),
                    provenance=json.loads(
                        row["signal_data_json"]
                    ),
                    proposition=reasoning.get(
                        "proposition", ""
                    ),
                    current_state=reasoning.get(
                        "current_state", None
                    ),
                    target_state=reasoning.get(
                        "target_state", None
                    ),
                    benefit=reasoning.get(
                        "benefit", "none"
                    ),
                    cost=reasoning.get(
                        "cost", "none"
                    ),
                    risk=reasoning.get(
                        "risk", "unknown"
                    ),
                    reason=reasoning.get(
                        "reason", ""
                    ),
                )
            )


        return signals