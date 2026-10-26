import json

from app.models.opportunity_assessment import OpportunityAssessment

from app.models.analysis_context import AnalysisContext
from app.models.media_context import MediaContext


class AnalysisRepository:
    """
    Persistence boundary for NAMOA analysis results.

    Responsibilities:

    - Persist technical analysis
    - Persist opportunity assessments

    Database connection lifecycle is owned by the caller.

    This class does not:
    - create media ownership records
    - run analysis
    - perform decisions
    - modify MediaContext
    - commit transactions
    """


    def __init__(self, connection, decision_signal_repository=None):
        self.connection = connection
        # Optional collaborator used only to attach the persisted
        # decision signals to a reconstructed OpportunityAssessment,
        # so queue/presentation reads can derive the proposed
        # transformation from data the system already persists.
        self.decision_signal_repository = (
            decision_signal_repository
        )


    def save_analysis(
        self,
        context: AnalysisContext,
        media_id: int,
        analysis_run_id: int,
    ) -> int:

        cursor = self.connection.cursor()

        media = context.media

        self._save_media_analysis(
            cursor,
            media_id,
            analysis_run_id,
            media
        )

        # Only genuine opportunities are persisted as opportunity
        # assessments. A "none" assessment records the preservation
        # conclusion through its decision signals; its absence from
        # this table is the established meaning of "no opportunity".
        if (
            context.assessment
            and context.assessment.opportunity_level != "none"
        ):

            self._save_opportunity_assessment(
                cursor,
                media_id,
                analysis_run_id,
                context
            )

        return media_id


    def _save_media_analysis(
        self,
        cursor,
        media_id: int,
        analysis_run_id: int,
        media: MediaContext,
    ):

        cursor.execute(
            """
            INSERT INTO media_analysis (
                media_id,
                analysis_run_id,
                duration,
                bitrate,
                resolution,
                video_codec,
                audio_tracks
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                media_id,
                analysis_run_id,
                media.duration,
                media.bitrate,
                f"{media.width}x{media.height}",
                media.video_codec,
                media.audio_channels,
            )
        )


    def _save_opportunity_assessment(
        self,
        cursor,
        media_id: int,
        analysis_run_id: int,
        context: AnalysisContext,
    ):

        assessment = context.assessment

        cursor.execute(
            """
            INSERT INTO opportunity_assessments (
                media_id,
                analysis_run_id,
                opportunity,
                score,
                confidence,
                estimated_saving_percent,
                risk,
                evidence_json,
                reasoning_json,
                contributing_rules_json,
                opportunity_level,
                priority_label,
                expected_saved_bytes,
                benefit,
                cost,
                preservation_reasons_json,
                suppressed_signals_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                media_id,
                analysis_run_id,
                assessment.opportunity,
                assessment.opportunity_score,
                assessment.confidence,
                assessment.estimated_saving_percent,
                assessment.risk,
                json.dumps(assessment.evidence),
                json.dumps(assessment.reasoning),
                json.dumps(assessment.contributing_rules),
                assessment.opportunity_level,
                assessment.priority_label,
                assessment.expected_saved_bytes,
                assessment.benefit,
                assessment.cost,
                json.dumps(assessment.preservation_reasons),
                json.dumps(assessment.suppressed_signals),
            )
        )

    def get_opportunity_assessment(
        self,
        analysis_run_id: int,
    ):

        import json

        from app.models.opportunity_assessment import (
            OpportunityAssessment
        )

        columns = self._opportunity_columns()

        row = self.connection.execute(
            f"""
            SELECT {columns}
            FROM opportunity_assessments
            WHERE analysis_run_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (
                analysis_run_id,
            ),
        ).fetchone()

        if row is None:
            return None

        # Historical rows (recorded before migration 029) have NULL
        # semantics columns; derive a level from the recorded score so
        # they remain meaningful.
        level = row["opportunity_level"]

        if level is None:
            level = self._derive_level(
                row["score"],
            )

        label = row["priority_label"]

        if label is None:
            from app.models.user_policy import (
                OPPORTUNITY_LEVEL_LABELS,
            )
            label = OPPORTUNITY_LEVEL_LABELS.get(
                level,
                OPPORTUNITY_LEVEL_LABELS["none"],
            )

        assessment = OpportunityAssessment(

            opportunity=row["opportunity"],

            opportunity_score=row["score"],

            confidence=row["confidence"],

            estimated_saving_percent=row[
                "estimated_saving_percent"
            ],

            risk=row["risk"],

            evidence=json.loads(
                row["evidence_json"] or "{}"
            ),

            reasoning=json.loads(
                row["reasoning_json"] or "[]"
            ),

            contributing_rules=json.loads(
                row["contributing_rules_json"] or "[]"
            ),

            opportunity_level=level,

            priority_label=label,

            expected_saved_bytes=row["expected_saved_bytes"],

            benefit=row["benefit"] or "none",

            cost=row["cost"] or "none",

            preservation_reasons=json.loads(
                row["preservation_reasons_json"] or "[]"
            ),

            suppressed_signals=json.loads(
                row["suppressed_signals_json"] or "[]"
            ),
        )

        # Attach the persisted decision signals so the assessment read
        # model matches the runtime model (which carries signals).
        # Purely a read enhancement of already-persisted data; no
        # signals are recomputed or reinterpreted.
        if self.decision_signal_repository is not None:

            assessment.signals = (
                self.decision_signal_repository
                .get_by_analysis_run(
                    analysis_run_id
                )
            )

        return assessment

    @staticmethod
    def _derive_level(score) -> str:
        """
        Derive an opportunity level from a recorded score for
        historical rows that predate migration 029.
        """

        try:
            value = float(score or 0.0)
        except (TypeError, ValueError):
            value = 0.0

        from app.decision_engine.fusion_engine.fusion_engine import (
            FusionEngine,
        )

        if value >= FusionEngine.LEVEL_STRONG:
            return "strong"
        if value >= FusionEngine.LEVEL_MEANINGFUL:
            return "meaningful"
        if value >= FusionEngine.LEVEL_WEAK:
            return "weak"
        return "none"

    def _opportunity_columns(self) -> str:
        """
        The SELECT list for opportunity assessment rows. Uses the
        extended schema when available and falls back to the base
        schema for pre-029 databases.
        """

        base = (
            "opportunity, score, confidence, "
            "estimated_saving_percent, risk, evidence_json, "
            "reasoning_json, contributing_rules_json"
        )

        columns = {
            row[1]
            for row in self.connection.execute(
                "PRAGMA table_info(opportunity_assessments)"
            ).fetchall()
        }

        if "opportunity_level" not in columns:
            return base

        return (
            base
            + ", opportunity_level, priority_label, "
            + "expected_saved_bytes, benefit, cost, "
            + "preservation_reasons_json, suppressed_signals_json"
        )

    def get_media_analysis(
        self,
        analysis_run_id: int,
    ):
        """
        Retrieve the persisted technical facts (media_analysis row)
        for one analysis run.

        Returns a MediaAnalysisRecord, or None when the run has no
        persisted analysis facts.
        """

        from app.models.media_analysis_record import (
            MediaAnalysisRecord,
        )

        row = self.connection.execute(
            """
            SELECT
                media_id,
                analysis_run_id,
                resolution,
                video_codec,
                duration,
                bitrate,
                audio_tracks,
                is_hdr,
                container,
                analysed_at
            FROM media_analysis
            WHERE analysis_run_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (
                analysis_run_id,
            ),
        ).fetchone()

        if row is None:
            return None

        return MediaAnalysisRecord(
            media_id=row[0],
            analysis_run_id=row[1],
            resolution=row[2],
            video_codec=row[3],
            duration=row[4],
            bitrate=row[5],
            audio_tracks=row[6],
            is_hdr=row[7],
            container=row[8],
            analysed_at=row[9],
        )
